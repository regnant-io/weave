# GitLab Repository Setup and Push Instructions

## Step 1: Create GitLab Project

1. Open browser and go to: https://gitlab.com
2. Sign in with username: `daudi.abinallah`
3. Click the "+" button (top right) → "New project/repository"
4. Choose "Create blank project"
5. Fill in project details:
   - **Project name**: `weave`
   - **Project URL**: `https://gitlab.com/daudi.abinallah/weave`
   - **Visibility Level**: Private (recommended) or Public
   - **Initialize repository with a README**: ❌ UNCHECK THIS (we already have code)
6. Click "Create project"

## Step 2: Push Code to GitLab

After creating the project, run these commands in your local repository:

```bash
# Push all code to GitLab
git push -u origin master
```

If you encounter authentication issues, you may need to set up SSH keys or use a personal access token:

### Option A: Using SSH (Recommended)

1. Generate SSH key (if you don't have one):
   ```bash
   ssh-keygen -t ed25519 -C "daudi.abinallah@gitlab.com"
   ```

2. Copy your public key:
   ```bash
   cat ~/.ssh/id_ed25519.pub
   ```

3. Add to GitLab:
   - Go to https://gitlab.com/-/profile/keys
   - Paste your public key
   - Give it a title (e.g., "Windows PC")
   - Click "Add key"

4. Update remote URL to use SSH:
   ```bash
   git remote set-url origin git@gitlab.com:daudi.abinallah/weave.git
   git push -u origin master
   ```

### Option B: Using Personal Access Token

1. Create token at: https://gitlab.com/-/profile/personal_access_tokens
2. Give it a name (e.g., "Weave Deploy Token")
3. Select scopes: `api`, `read_repository`, `write_repository`
4. Click "Create personal access token"
5. Copy the token (you won't see it again!)

6. Push with token:
   ```bash
   git remote set-url origin https://oauth2:<YOUR_TOKEN>@gitlab.com/daudi.abinallah/weave.git
   git push -u origin master
   ```

## Step 3: Verify Upload

1. Go to https://gitlab.com/daudi.abinallah/weave
2. You should see all your files including:
   - `README.md`
   - `docker-compose.yml`
   - `deploy-kamatera.sh`
   - `DEPLOY.md`
   - `frontend/` and `backend/` directories

## Step 4: Update Deployment Script

The deployment script (`deploy-kamatera.sh`) currently has a placeholder for the git clone command. After pushing to GitLab, you may want to update it:

1. Open `deploy-kamatera.sh`
2. Find the line with the git clone comment
3. Uncomment and ensure it reads:
   ```bash
   git clone https://gitlab.com/daudi.abinallah/weave.git .
   ```
4. Commit and push the change:
   ```bash
   git add deploy-kamatera.sh
   git commit -m "Update deployment script with GitLab repository URL"
   git push
   ```

## Step 5: Deploy to Kamatera

Now you can deploy to Kamatera! On your Kamatera server:

```bash
# Download and run the deployment script
curl -o deploy-kamatera.sh https://gitlab.com/daudi.abinallah/weave/-/raw/master/deploy-kamatera.sh
chmod +x deploy-kamatera.sh
./deploy-kamatera.sh
```

Or clone the entire repository:

```bash
git clone https://gitlab.com/daudi.abinallah/weave.git
cd weave
chmod +x deploy-kamatera.sh
./deploy-kamatera.sh
```

## Troubleshooting

### "Repository not found" error
- Make sure the project was created successfully on GitLab
- Check the repository URL is correct
- Verify you have push permissions

### Authentication failed
- Use SSH keys or personal access token (see options above)
- Make sure your credentials are correct
- Check if 2FA is enabled on your account (use token if yes)

### Large files warning
- The `.venv312` directory should be ignored by `.gitignore`
- If you get warnings about large files, make sure `.gitignore` is working
- Run `git rm --cached -r backend/.venv312` if needed

## Repository Information

- **Repository URL**: https://gitlab.com/daudi.abinallah/weave
- **Owner**: Daud Idd (@daudi.abinallah)
- **Description**: Bilingual (Kiswahili/English) study and research workspace for Tanzanian students and researchers
- **Default Branch**: master

## Next Steps

After pushing to GitLab:

1. ✅ Update repository description and topics on GitLab
2. ✅ Add project avatar/logo
3. ✅ Configure CI/CD pipelines (optional)
4. ✅ Set up branch protection rules
5. ✅ Add team members with appropriate permissions
6. ✅ Deploy to Kamatera using the deployment script

## Support

If you encounter issues:
- Check GitLab status: https://status.gitlab.com
- GitLab documentation: https://docs.gitlab.com
- Project documentation: See README.md and DEPLOY.md
