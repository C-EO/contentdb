# ContentDB
# Copyright (C) 2018-21 rubenwardy
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import typing
from functools import wraps
from typing import List

import sqlalchemy.orm
from flask import abort, redirect, url_for, request
from flask_login import current_user
from sqlalchemy import or_, and_
from sqlalchemy.orm import sessionmaker

from app.models import User, NotificationType, Package, UserRank, Notification, db, AuditSeverity, AuditLogEntry, ThreadReply, Thread, PackageState, PackageType, PackageAlias


def get_package_by_info(author, name):
	user = User.query.filter_by(username=author).first()
	if user is None:
		return None

	package = Package.query.filter_by(name=name, author_id=user.id) \
		.filter(Package.state!=PackageState.DELETED).first()
	if package is None:
		return None

	return package


def is_package_page(f):
	@wraps(f)
	def decorated_function(*args, **kwargs):
		if not ("author" in kwargs and "name" in kwargs):
			abort(400)

		author = kwargs["author"]
		name = kwargs["name"]

		package = get_package_by_info(author, name)
		if package is None:
			package = get_package_by_info(author, name + "_game")
			if package and package.type == PackageType.GAME:
				args = dict(kwargs)
				args["name"] = name + "_game"
				return redirect(url_for(request.endpoint, **args))

			alias = PackageAlias.query.filter_by(author=author, name=name).first()
			if alias is not None:
				args = dict(kwargs)
				args["author"] = alias.package.author.username
				args["name"] = alias.package.name
				return redirect(url_for(request.endpoint, **args))

			abort(404)

		del kwargs["author"]
		del kwargs["name"]
		return f(package=package, *args, **kwargs)

	return decorated_function


def add_notification(target, causer: User, type: NotificationType, title: str, url: str,
			package: Package = None, session: sqlalchemy.orm.Session = None):
	if session is None:
		session = db.session

	try:
		iter(target)
		for x in target:
			add_notification(x, causer, type, title, url, package, session)
		return
	except TypeError:
		pass

	if target.rank.at_least(UserRank.NEW_MEMBER) and target != causer:
		session.query(Notification) \
				.filter_by(user=target, causer=causer, type=type, title=title, url=url, package=package) \
				.delete()
		notif = Notification(target, causer, type, title, url, package)
		session.add(notif)


def add_audit_log(severity: AuditSeverity, causer: User, title: str, url: typing.Optional[str],
			package: Package = None, description: str = None):
	entry = AuditLogEntry(causer, severity, title, url, package, description)
	db.session.add(entry)


def clear_notifications(url):
	if current_user.is_authenticated:
		Notification.query.filter_by(user=current_user, url=url).delete()
		db.session.commit()


def get_system_user():
	system_user = User.query.filter_by(username="ContentDB").first()
	assert system_user
	return system_user


def add_system_notification(target, type: NotificationType, title: str, url: str, package: Package = None):
	return add_notification(target, get_system_user(), type, title, url, package)


def add_system_audit_log(severity: AuditSeverity, title: str, url: str, package=None, description=None):
	return add_audit_log(severity, get_system_user(), title, url, package, description)


def post_bot_message(package: Package, title: str, message: str, session=None):
	if session is None:
		session = db.session

	system_user = get_system_user()

	thread = package.threads.filter_by(author=system_user).first()
	if not thread:
		thread = Thread()
		thread.package = package
		thread.title = "Messages for '{}'".format(package.title)
		thread.author = system_user
		thread.private = True
		thread.watchers.extend(package.maintainers)
		session.add(thread)
		session.flush()

	reply = ThreadReply()
	reply.thread = thread
	reply.author = system_user
	reply.comment = "**{}**\n\n{}\n\nThis is an automated message, but you can reply if you need help".format(title, message)
	session.add(reply)

	add_notification(thread.watchers, system_user, NotificationType.BOT, title, thread.get_view_url(), thread.package, session)

	thread.replies.append(reply)


def post_to_approval_thread(package: Package, user: User, message: str, is_status_update=True, create_thread=False):
	thread = package.review_thread
	if thread is None:
		if create_thread:
			thread = Thread()
			thread.author = user
			thread.title = "Package approval comments"
			thread.private = True
			thread.package = package
			db.session.add(thread)
			db.session.flush()
			package.review_thread = thread
		else:
			return

	reply = ThreadReply()
	reply.thread = thread
	reply.author = user
	reply.is_status_update = is_status_update
	reply.comment = message
	db.session.add(reply)

	if is_status_update:
		msg = f"{message} - {thread.title}"
	else:
		msg = f"New comment on '{thread.title}'"

	add_notification(thread.watchers, user, NotificationType.THREAD_REPLY, msg, thread.get_view_url(), package)

	thread.replies.append(reply)


def get_games_from_csv(session: sqlalchemy.orm.Session, csv: str) -> List[Package]:
	return get_games_from_list(session, [name.strip() for name in csv.split(",")])


def get_games_from_list(session: sqlalchemy.orm.Session, supported_games_raw: list[str]) -> List[Package]:
	retval = []
	for game_name in supported_games_raw:
		if game_name.endswith("_game"):
			game_name = game_name[:-5]
		games = session.query(Package).filter(and_(Package.state==PackageState.APPROVED, Package.type==PackageType.GAME,
				or_(Package.name==game_name, Package.name==game_name + "_game"))).all()
		retval.extend(games)

	return retval


def create_session():
	return sessionmaker(bind=db.engine)()
