Current runner version: '2.337.0'
Runner Image Provisioner
Operating System
Runner Image
GITHUB_TOKEN Permissions
Secret source: Actions
Cache mode: write
Prepare workflow directory
Prepare all required actions
Getting action download info
Download action repository 'actions/checkout@v4' (SHA:11d5960a326750d5838078e36cf38b85af677262)
Complete job name: update
0s
Run actions/checkout@v4
Syncing repository: harushibu12/rss-static
Getting Git version info
Temporarily overriding HOME='/home/runner/work/_temp/9bd50676-e7ec-4a42-a83c-96264052b37d' before making global git config changes
Adding repository directory to the temporary git global config as a safe directory
/usr/bin/git config --global --add safe.directory /home/runner/work/rss-static/rss-static
Deleting the contents of '/home/runner/work/rss-static/rss-static'
Initializing the repository
Disabling automatic garbage collection
Setting up auth
Fetching the repository
Determining the checkout info
/usr/bin/git sparse-checkout disable
/usr/bin/git config --local --unset-all extensions.worktreeConfig
Checking out the ref
/usr/bin/git log -1 --format=%H
53ed07742104bbfbdac6cb958f1beaddda041d0f
1s
Run python update.py
================================
EE Times RSS更新開始
================================
トップページ取得成功: 69256 bytes
トップページ内リンク数: 212
EE Times記事URL: 0
記事URLが1件もありません。
既存JSONを維持します。
1s
Run git config user.name "github-actions[bot]"
From https://github.com/harushibu12/rss-static
 * branch            main       -> FETCH_HEAD
HEAD is now at 53ed077 Update update.py
変更なし。コミットしません。
0s
Post job cleanup.
/usr/bin/git version
git version 2.55.0
Temporarily overriding HOME='/home/runner/work/_temp/58f1af72-7571-4ad3-9bae-9f7784e962f3' before making global git config changes
Adding repository directory to the temporary git global config as a safe directory
/usr/bin/git config --global --add safe.directory /home/runner/work/rss-static/rss-static
/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
http.https://github.com/.extraheader
/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
/usr/bin/git config --local --name-only --get-regexp ^includeIf\.gitdir:
/usr/bin/git submodule foreach --recursive git config --local --show-origin --name-only --get-regexp remote.origin.url
