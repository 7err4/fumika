# Proving authorship (free, no trademark needed)

Copyright exists from the moment the code is written. What matters if someone clones the repo and calls it theirs is being
able to show **that it is yours** and **since when**. Three free steps do that.

## 1. Signed commits as 7err4

GitHub then shows "Verified" on every commit. Do this **only in this repository** (local config) - the global git identity on
this PC belongs to another account and must not appear here.

```bash
# once: a signing key for the 7err4 identity (choose a passphrase)
ssh-keygen -t ed25519 -C "344930606+7err4@users.noreply.github.com" -f ~/.ssh/7err4_signing

# in this repository only
git config --local user.name 7err4
git config --local user.email 344930606+7err4@users.noreply.github.com
git config --local gpg.format ssh
git config --local user.signingkey ~/.ssh/7err4_signing.pub
git config --local commit.gpgsign true
git config --local tag.gpgsign true
```

Then, logged in as **7err4** on GitHub: Settings -> SSH and GPG keys -> New SSH key -> Key type **Signing Key**, paste the
content of `~/.ssh/7err4_signing.pub`.

Check: `git log --show-signature -1` after the next commit; on GitHub the commit shows "Verified".

## 2. Signed release tags

```bash
git tag -s v0.1.0 -m "Fumika 0.1.0"
git push origin v0.1.0
```

## 3. An independent, dated archive

After the repository is public: https://archive.softwareheritage.org/save/ -> enter the GitHub URL -> "Submit". Software
Heritage keeps a permanent, timestamped copy that does not depend on GitHub. Repeat after each release.

## If someone copies it anyway

- GitHub: DMCA takedown notice (https://github.com/contact/dmca) for copies that remove the copyright notice or claim
  authorship. Point to this repository, its signed history and the Software Heritage archive.
- Civitai and other sites: report as copyright infringement with the same evidence.

Not legal advice.
