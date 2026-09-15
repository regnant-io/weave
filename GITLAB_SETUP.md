# Optional GitLab mirror

GitHub is the active `origin`: `https://github.com/regnant-io/weave.git`.
Use a second remote if the project also needs a private GitLab mirror; replacing
`origin` makes deployment instructions and operator expectations diverge.

1. Create an empty GitLab project without a generated README.
2. Add its SSH URL as a separate remote:

   ```bash
   git remote add gitlab git@gitlab.com:<group>/weave.git
   git push -u gitlab HEAD
   ```

3. Confirm both remotes with `git remote -v`.
4. Configure branch protection and CI secret scanning in the GitLab project.

Prefer SSH or a credential manager. Do not embed personal access tokens in a
remote URL or command: Git stores remote URLs in `.git/config`, and commands may
also remain in shell history.

To deploy from the mirror, provide its clone URL to the helper without editing
the script:

```bash
export WEAVE_REPOSITORY_URL="git@gitlab.com:<group>/weave.git"
export NGROK_AUTHTOKEN="<token from your ngrok account>"
./deploy-kamatera.sh
```

Use the production topology and preflight checklist in [`DEPLOY.md`](DEPLOY.md).
