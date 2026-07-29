# iOS 15 Compatibility Fixes - Complete Summary

## Problem
The Weave application was crashing on iPad running iOS 15.8.8 (and other older browsers) with two critical errors:

1. **React Error #31**: "Objects are not valid as a React child"
2. **Service Worker Failures**: Network error responses

## Root Causes Identified

### 1. React Error #31 - Rendering Objects as React Children
The application was attempting to render raw JavaScript objects directly in React components, which causes React to crash. This happened in multiple components when API responses weren't properly normalized.

### 2. Service Worker Navigation Issues
The service worker was not returning valid Response objects for navigation requests, causing the browser to crash when navigating between pages.

### 3. Limited JavaScript Support in iOS 15
- Promise.all with inline catch blocks can fail
- Arrow functions in setTimeout may not execute properly
- Some modern JavaScript features not fully supported

## Fixes Applied

### A. Frontend Component Fixes

#### 1. **SettingsClient.tsx** - Added `asText()` Helper Function
```typescript
/**
 * Coerce anything the API hands us into a renderable string.
 * React throws error #31 for objects. Every value that crosses 
 * the network boundary goes through here.
 */
function asText(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v || "—";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(asText).join(", ");
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.name === "string") return o.name;
    if (typeof o.label === "string") return o.label;
    try {
      return JSON.stringify(v);
    } catch {
      return "—";
    }
  }
  return String(v);
}
```

**Why**: This ensures that any data from the API is converted to a string before being rendered, preventing React error #31.

#### 2. **OllamaSettings.tsx** - Replaced Promise.all with Sequential Awaits
**Before**:
```typescript
const [cfg, cat] = await Promise.all([
  fetch("/api/ollama-config").then(r => r.json()).catch(() => ({})),
  fetchCatalog()
]);
```

**After**:
```typescript
const refresh = useCallback(async () => {
  setError(null);
  let cfg: { ollama_host?: unknown; ollama_model?: unknown } = {};
  try {
    const res = await fetch("/api/ollama-config", { cache: "no-store" });
    if (res.ok) cfg = await res.json();
  } catch {
    setError(sw ? "Imeshindwa kupakia mipangilio." : "Could not load the current configuration.");
  }
  const cat = await fetchCatalog();
  // ... rest of the code
}, [sw]);
```

**Why**: iOS 15 Safari has issues with Promise.all when inline catch blocks are used. Sequential awaits with try-catch are more reliable.

#### 3. **OllamaSettings.tsx** - Replaced Arrow Functions in setTimeout
**Before**:
```typescript
setTimeout(() => setSaved(false), 2200);
```

**After**:
```typescript
setTimeout(function() { setSaved(false); }, 2200);
```

**Why**: Traditional function syntax is more compatible with older JavaScript engines.

#### 4. **ProjectMemoryClient.tsx** - Added Try-Catch and Sequential Operations
- Replaced concurrent operations with sequential awaits
- Added comprehensive error handling
- Used traditional functions instead of arrow functions in callbacks

#### 5. **Health API Response Fix** in `frontend/src/lib/api.ts`
**Before**:
```typescript
const health = (await fetch("/api/health").then(r => r.json())) as Health;
return health;
```

**After**:
```typescript
const response = await fetch("/api/health");
const data = await response.json();
return {
  llm_engine: data.llm_engine,
  embedding_backend: data.embedding_backend,
  sandbox_backend: data.sandbox_backend,
  database: data.database,
  tools: data.tools || [],
  capabilities: data.capabilities || {}
};
```

**Why**: Explicitly extracting needed fields prevents passing unexpected object shapes to React components.

### B. Service Worker Fixes (`frontend/public/sw.js`)

#### 1. Fixed Navigation Request Handling
**Before**:
```javascript
if (event.request.mode === "navigate") {
  return; // Just returned undefined
}
```

**After**:
```javascript
if (event.request.mode === "navigate") {
  event.respondWith(fetch(event.request));
  return;
}
```

**Why**: Service workers MUST return a valid Response for navigation requests. Returning undefined causes crashes.

#### 2. Updated Cache Version
Changed from `v1` to `v2` to force all clients to update their service worker and clear old caches.

### C. Browser Compatibility Configuration

#### 1. **.browserslistrc** - Set Minimum Browser Support
```
iOS >= 12
Safari >= 12
Chrome >= 80
Firefox >= 78
Edge >= 88
not dead
not op_mini all
```

**Why**: Ensures build tools transpile modern JavaScript to syntax compatible with iOS 12+.

#### 2. **package.json** - Added Core-js Polyfills
```json
"dependencies": {
  "core-js": "^3.39.0",
  ...
}
```

**Why**: Provides polyfills for modern JavaScript features not available in older browsers.

#### 3. **next.config.mjs** - Disabled SWC Minification
```javascript
swcMinify: false
```

**Why**: SWC minifier can produce code that breaks on older browsers. Using default Terser instead.

### D. Deployment Infrastructure

#### Created `rebuild-frontend.sh` for Complete Rebuilds
```bash
#!/bin/bash
set -e

echo "🔄 Rebuilding frontend with ALL fixes..."

cd /opt/weave

# Pull latest code
git fetch origin
git reset --hard origin/master

# Stop and remove old frontend
sudo docker-compose stop frontend
sudo docker-compose rm -f frontend
sudo docker rmi weave-frontend 2>/dev/null || true

# Clear Docker build cache
sudo docker builder prune -f

# Rebuild from scratch
sudo docker-compose build --no-cache --pull frontend

# Start frontend
sudo docker-compose up -d frontend
```

**Why**: Ensures complete rebuild without cached layers when iOS fixes are deployed.

## Deployment Instructions

### On Kamatera Server:
```bash
# Navigate to project
cd /opt/weave

# Pull latest changes
git pull origin master

# Run complete rebuild
./rebuild-frontend.sh

# Verify new bundle hash (should NOT be 4bd1b696)
# Check browser console for new bundle filename
```

### On iPad (iOS 15.8.8):
```
1. Close Safari completely (swipe up from app switcher)
2. Open Settings > Safari > Clear History and Website Data
3. Reopen Safari and navigate to your ngrok URL
4. Test opening projects and settings page
```

## Files Modified

### Frontend Components:
- `frontend/src/components/SettingsClient.tsx` - Added asText() helper
- `frontend/src/components/OllamaSettings.tsx` - Sequential awaits, traditional functions
- `frontend/src/components/ProjectMemoryClient.tsx` - Try-catch, sequential ops
- `frontend/src/app/app/projects/[id]/page.tsx` - Null check for hypotheses

### API Layer:
- `frontend/src/lib/api.ts` - Explicit field extraction for health API

### Service Worker:
- `frontend/public/sw.js` - Fixed navigation responses, bumped cache version

### Configuration:
- `frontend/.browserslistrc` - iOS 12+ compatibility
- `frontend/package.json` - Added core-js polyfills
- `frontend/next.config.mjs` - Disabled SWC minifier

### Build Scripts:
- `frontend/src/app/layout.tsx` - Fixed JSX syntax error
- `rebuild-frontend.sh` - Complete rebuild script

## Testing Checklist

### ✅ Must Test on iPad iOS 15.8.8:
- [ ] Home page loads without errors
- [ ] Can navigate to Projects page
- [ ] Can open a project (click on project card)
- [ ] Project details page renders correctly
- [ ] Can navigate to Settings page
- [ ] Settings page displays without crash
- [ ] Can update Ollama URL in settings
- [ ] Changes save successfully
- [ ] No React error #31 in console
- [ ] No service worker errors in console

### ✅ Must Verify:
- [ ] New bundle hash (not `4bd1b696`)
- [ ] Service worker updated to v2
- [ ] No objects rendered as React children
- [ ] All API responses properly normalized

## Technical Notes

### Why These Fixes Work:

1. **asText() Helper**: Acts as a defensive barrier between API data and React's renderer. Even if the API returns unexpected shapes, asText() will convert them to strings.

2. **Sequential Awaits**: Older JavaScript engines struggle with Promise.all when error handling is complex. Sequential operations are more predictable.

3. **Traditional Functions**: Arrow functions rely on lexical `this` binding which can behave differently in older engines, especially in callbacks.

4. **Service Worker Responses**: Service workers intercept ALL network requests. Failing to return a Response object breaks the entire navigation flow.

5. **Browserslist + Polyfills**: Ensures Next.js transpiles modern syntax and includes polyfills for missing features.

## Known Limitations

- Full iOS 15 compatibility requires manual testing - automated tests can't catch all edge cases
- Some very old Android browsers (< Chrome 80) may still have issues
- Regex lookbehind in dependencies can still cause parse errors - we've removed problematic markdown libraries

## Git Commits

All fixes included in commit:
```
commit 2fa38393c7597bebc224b94fdae245e7f710942f
Author: Derrick <derrick@weave.local>
Date:   Wed Jul 29 11:56:03 2026 +0200

    Major update: add workspace features, memory service, interactions API, and stats
    - iOS 15 compatibility fixes
    - Add workspace API endpoints
    - Add memory service for contextual recall
    - Add interactions tracking
    - Add statistics API
    - Add threads support
    - Update runtime and config
    - Enhance backend APIs
```

Pushed to GitLab: ✅ https://gitlab.com/daudi.abinallah/weave

## Next Steps

1. **Deploy on Server**: Run `./rebuild-frontend.sh` on Kamatera
2. **Clear iPad Cache**: Settings > Safari > Clear History and Website Data
3. **Test Thoroughly**: Go through the testing checklist above
4. **Monitor Logs**: Check both browser console and server logs for errors
5. **Report Results**: Verify bundle hash changed and crashes are resolved

---

**Status**: All fixes committed and pushed to GitLab ✅  
**Deployed**: Waiting for server rebuild  
**Bundle Hash**: Currently `4bd1b696` (should change after rebuild)  
**Last Updated**: July 29, 2026
