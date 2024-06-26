# ContentDB
# Copyright (C) rubenwardy
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

import os

from app.utils.git import get_latest_tag, get_latest_commit, clone_repo, get_commit_list

test_repo = "https://gitlab.com/rubenwardy/testmod"
master_head = "23d12265ff6de84548b2e3e90dc7351a54f63f00"
test_branch_head = "51b54f00c3b3d712417a1cc4bfaa6cbdc7aac3fc"
v4_commit = "c07d27c3a466d2102d1ba5473d172c74e6b3e0d7"
latest_tag_name = "v5"
latest_tag_commit = "23d12265ff6de84548b2e3e90dc7351a54f63f00"
latest_tag_message = """
* One thing
* Second
* Third
""".strip()
random_commit = "84a2e53ff046eacbdbb80f3a00c58510885fefca"


def test_get_latest_tag():
	tag, commit, message = get_latest_tag(test_repo)
	assert tag == latest_tag_name
	assert commit == latest_tag_commit
	assert message == latest_tag_message


def test_get_latest_commit():
	assert get_latest_commit(test_repo) == master_head
	assert get_latest_commit(test_repo, "test-branch") == test_branch_head


def test_get_commit_list():
	result = get_commit_list(test_repo, "4fd0d06df2cc502b0cbc3ee932217b540f0d92ad", "23d12265ff6de84548b2e3e90dc7351a54f63f00")
	assert result == [
		"Update .cdb.json",
		"Update mod.conf",
		"Update mod.conf",
		"Update mod.conf",
		"Update mod.conf",
		"Update mod.conf",
		"Update mod.conf",
	]


def test_git_clone_head():
	with clone_repo(test_repo, recursive=True) as repo:
		assert repo.head.commit.hexsha == master_head
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "init.lua"))
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "chatcmdbuilder", "init.lua"))
		assert not os.path.isfile(os.path.join(repo.working_tree_dir, "test-branch.txt"))


def test_git_clone_branch():
	with clone_repo(test_repo, "test-branch", recursive=True) as repo:
		assert repo.head.commit.hexsha == test_branch_head
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "init.lua"))
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "chatcmdbuilder", "init.lua"))
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "test-branch.txt"))


def test_git_clone_tag():
	with clone_repo(test_repo, "v4", recursive=True) as repo:
		assert repo.head.commit.hexsha == v4_commit

		# v4 isn't on the master branch, let's check there's no master branch files
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "init.lua"))
		assert not os.path.isfile(os.path.join(repo.working_tree_dir, "chatcmdbuilder", "init.lua"))
		assert not os.path.isfile(os.path.join(repo.working_tree_dir, "test-branch.txt"))


def test_git_clone_commit():
	with clone_repo(test_repo, random_commit, recursive=True) as repo:
		assert repo.head.commit.hexsha == random_commit
		assert os.path.isfile(os.path.join(repo.working_tree_dir, "init.lua"))
		assert not os.path.isfile(os.path.join(repo.working_tree_dir, "chatcmdbuilder", "init.lua"))
		assert not os.path.isfile(os.path.join(repo.working_tree_dir, "test-branch.txt"))
