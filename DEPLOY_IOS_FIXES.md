# Quick Deployment Guide - iOS 15 Fixes

## ⚠️ CRITICAL: The frontend container MUST be rebuilt on the server

The bundle hash is currently `4bd1b696` - this means the iOS fixes are NOT deployed yet.

## On Kamatera Server (SSH):

```bash
# 1. Navigate to project directory
cd /opt/weave

# 2. Pull latest changes from GitLab
sudo git fetch origin
sudo git reset --hard origin/master

# 3. Run complete frontend rebuild (removes old container, clears cache, rebuilds)
sudo chmod +x rebuild-frontend.sh
./rebuild-frontend.sh
```

**Expected Output:**
- Docker will rebuild the frontend (takes 1-2 minutes)
- You'll see "✅ Frontend rebuilt successfully!"
- The new bundle hash will be different from `4bd1b696`

## On iPad iOS 15.8.8:

```
1. Close Safari completely
   - Double-press home button (or swipe up)
   - Swipe Safari up to close it completely

2. Clear Safari cache
   - Open Settings
   - Scroll to Safari
   - Tap "Clear History and Website Data"
   - Confirm

3. Reopen Safari
   - Navigate to your ngrok URL
   - Test the following:
     ✓ Open a project
     ✓ Navigate to Settings
     ✓ Update Ollama URL
     ✓ Check browser console for errors (no React #31)
```

## How to Get ngrok URL:

```bash
# On Kamatera server
curl http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"https://[^"]*"' | head -1 | cut -d'"' -f4
```

Or visit: `http://YOUR_SERVER_IP:4040` in a browser

## Verification Checklist:

- [ ] Git pull completed successfully
- [ ] Frontend container rebuilt (new bundle hash visible)
- [ ] Service worker version bumped to v2
- [ ] iPad can open projects without crashing
- [ ] Settings page loads without React error #31
- [ ] Ollama settings can be updated
- [ ] No console errors on iPad

## Troubleshooting:

### If bundle hash is still `4bd1b696`:
```bash
# Force complete cleanup
cd /opt/weave
sudo docker-compose down
sudo docker system prune -af
sudo docker-compose build --no-cache frontend
sudo docker-compose up -d
```

### If iPad still crashes:
1. Clear Safari cache again (Settings > Safari > Clear History)
2. Try in Private Browsing mode
3. Check server logs: `sudo docker-compose logs -f frontend`
4. Check browser console for specific error messages

### If changes aren't visible:
- Hard refresh: Hold Shift + tap refresh in Safari
- Check bundle hash in console: Look for `*.js` files in Network tab
- Verify service worker updated: Application tab > Service Workers

## Files Changed in This Update:

**Frontend Components:**
- SettingsClient.tsx (added asText() helper)
- OllamaSettings.tsx (sequential awaits)
- ProjectMemoryClient.tsx (try-catch blocks)

**Service Worker:**
- sw.js (fixed navigation, v2 cache)

**Config:**
- .browserslistrc (iOS 12+ support)
- package.json (core-js polyfills)
- next.config.mjs (disabled SWC)

## Support:

If issues persist after deployment:
1. Capture browser console logs (screenshot)
2. Check server logs: `sudo docker-compose logs -f frontend backend`
3. Verify bundle hash changed from `4bd1b696`
4. Test on different iOS device if available

---

**Status**: Ready to deploy ✅  
**GitLab**: https://gitlab.com/daudi.abinallah/weave  
**Last Updated**: July 29, 2026
