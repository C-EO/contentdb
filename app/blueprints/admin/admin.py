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

from flask import redirect, render_template, url_for, request, flash
from flask_login import current_user, login_user
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, BooleanField
from wtforms.validators import InputRequired, Length, Optional
from app.utils import rank_required, add_audit_log, add_notification, get_system_user, nonempty_or_none, \
	get_int_or_abort
from . import bp
from .actions import actions
from app.models import UserRank, Package, db, PackageState, User, AuditSeverity, NotificationType, PackageAlias
from ...querybuilder import QueryBuilder


@bp.route("/admin/", methods=["GET", "POST"])
@rank_required(UserRank.EDITOR)
def admin_page():
	if request.method == "POST" and current_user.rank.at_least(UserRank.ADMIN):
		action = request.form["action"]
		if action in actions:
			ret = actions[action]["func"]()
			if ret:
				return ret

		else:
			flash("Unknown action: " + action, "danger")

	return render_template("admin/list.html", actions=actions)


class SwitchUserForm(FlaskForm):
	username = StringField("Username")
	submit = SubmitField("Switch")


@bp.route("/admin/switchuser/", methods=["GET", "POST"])
@rank_required(UserRank.ADMIN)
def switch_user():
	form = SwitchUserForm(formdata=request.form)
	if form.validate_on_submit():
		user = User.query.filter_by(username=form.username.data).first()
		if user is None:
			flash("Unable to find user", "danger")
		elif login_user(user):
			return redirect(url_for("users.profile", username=current_user.username))
		else:
			flash("Unable to login as user", "danger")

	# Process GET or invalid POST
	return render_template("admin/switch_user.html", form=form)


class SendNotificationForm(FlaskForm):
	title = StringField("Title", [InputRequired(), Length(1, 300)])
	url = StringField("URL", [InputRequired(), Length(1, 100)], default="/")
	submit = SubmitField("Send")


@bp.route("/admin/send-notification/", methods=["GET", "POST"])
@rank_required(UserRank.ADMIN)
def send_bulk_notification():
	form = SendNotificationForm(request.form)
	if form.validate_on_submit():
		add_audit_log(AuditSeverity.MODERATION, current_user,
				"Sent bulk notification", url_for("admin.admin_page"), None, form.title.data)

		users = User.query.filter(User.rank >= UserRank.NEW_MEMBER).all()
		add_notification(users, get_system_user(), NotificationType.OTHER, form.title.data, form.url.data, None)
		db.session.commit()

		return redirect(url_for("admin.admin_page"))

	return render_template("admin/send_bulk_notification.html", form=form)


@bp.route("/admin/restore/", methods=["GET", "POST"])
@rank_required(UserRank.EDITOR)
def restore():
	if request.method == "POST":
		target = request.form["submit"]
		if "Review" in target:
			target = PackageState.READY_FOR_REVIEW
		elif "Changes" in target:
			target = PackageState.CHANGES_NEEDED
		else:
			target = PackageState.WIP

		package = Package.query.get(request.form["package"])
		if package is None:
			flash("Unknown package", "danger")
		else:
			package.state = target

			add_audit_log(AuditSeverity.EDITOR, current_user, f"Restored package to state {target.value}",
						  package.get_url("packages.view"), package)

			db.session.commit()
			return redirect(package.get_url("packages.view"))

	deleted_packages = Package.query \
		.filter(Package.state == PackageState.DELETED) \
		.join(Package.author) \
		.order_by(db.asc(User.username), db.asc(Package.name)) \
		.all()

	return render_template("admin/restore.html", deleted_packages=deleted_packages)


class TransferPackageForm(FlaskForm):
	old_username = StringField("Old Username", [InputRequired()])
	new_username = StringField("New Username", [InputRequired()])
	package = StringField("Package", [Optional()])
	remove_maintainer = BooleanField("Remove current owner from maintainers")
	submit = SubmitField("Transfer")


def perform_transfer(form: TransferPackageForm):
	query = Package.query.filter(Package.author.has(username=form.old_username.data))
	if nonempty_or_none(form.package.data):
		query = query.filter_by(name=form.package.data)

	packages = query.all()
	if len(packages) == 0:
		flash("Unable to find package(s)", "danger")
		return

	new_user = User.query.filter_by(username=form.new_username.data).first()
	if new_user is None:
		flash("Unable to find new user", "danger")
		return

	names = [x.name for x in packages]
	already_existing = Package.query.filter(Package.author_id == new_user.id, Package.name.in_(names)).all()
	if len(already_existing) > 0:
		existing_names = [x.name for x in already_existing]
		flash("Unable to transfer packages as names exist at destination: " + ", ".join(existing_names), "danger")
		return

	for package in packages:
		if form.remove_maintainer.data:
			package.maintainers.remove(package.author)
		package.author = new_user
		package.maintainers.append(new_user)
		package.aliases.append(PackageAlias(form.old_username.data, package.name))

		add_audit_log(AuditSeverity.MODERATION, current_user,
				f"Transferred {form.old_username.data}/{package.name} to {form.new_username.data}",
				package.get_url("packages.view"), package)

	db.session.commit()

	flash("Transferred " + ", ".join([x.name for x in packages]), "success")

	return redirect(url_for("admin.transfer"))


@bp.route("/admin/transfer/", methods=["GET", "POST"])
@rank_required(UserRank.MODERATOR)
def transfer():
	form = TransferPackageForm(formdata=request.form)
	if form.validate_on_submit():
		ret = perform_transfer(form)
		if ret is not None:
			return ret

	# Process GET or invalid POST
	return render_template("admin/transfer.html", form=form)


@bp.route("/admin/storage/")
@rank_required(UserRank.EDITOR)
def storage():
	qb = QueryBuilder(request.args, cookies=True)
	qb.only_approved = False
	packages = qb.build_package_query().all()

	show_all = len(packages) < 100
	min_size = get_int_or_abort(request.args.get("min_size"), 0 if show_all else 50)

	data = []
	for package in packages:
		size_releases = sum([x.file_size_bytes for x in package.releases])
		size_screenshots = sum([x.file_size_bytes for x in package.screenshots])
		latest_release = package.releases.first()
		size_latest = latest_release.file_size_bytes if latest_release else 0
		size_total = size_releases + size_screenshots
		if size_total > min_size*1024*1024:
			data.append([package, size_total, size_releases, size_screenshots, size_latest])

	data.sort(key=lambda x: x[1], reverse=True)
	return render_template("admin/storage.html", data=data)
