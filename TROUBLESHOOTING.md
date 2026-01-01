# 🔧 Dosed Troubleshooting Guide

## 🐛 Common Issues & Fixes

---

## ❌ Issue: "lucide is not defined"

### **Problem:**
JavaScript error: `Uncaught ReferenceError: lucide is not defined`

### **Cause:**
Lucide icons library not loading from CDN (slow connection, CDN down, or blocked)

### **Fix Applied:**
✅ Added fallback emoji icons if Lucide doesn't load  
✅ Added safety checks before calling `lucide.createIcons()`  
✅ App now works even if Lucide fails to load  

### **What You'll See:**
- **If Lucide loads:** Beautiful icon set ✨
- **If Lucide fails:** Emoji icons instead (🌡️💊📋)

### **No action needed** - the app handles this automatically!

---

## ❌ Issue: Child Not Saving

### **Problem:**
Adding a child doesn't save, disappears on refresh

### **Possible Causes:**

#### **1. Incognito/Private Mode**
**Solution:** Use normal browser window (not private/incognito)

#### **2. Browser Blocking localStorage**
**Test:**
1. Open browser console (F12)
2. Type: `localStorage.setItem('test', 'hello')`
3. Type: `localStorage.getItem('test')`
4. Should return `"hello"`

**If it fails:**
- Check browser privacy settings
- Allow cookies for the site
- Disable strict tracking protection

**Chrome:** Settings → Privacy → Site Settings → Cookies → Allow  
**Safari:** Settings → Safari → Privacy → Uncheck "Block all cookies"  
**Firefox:** Settings → Privacy → Standard (not Strict)

#### **3. Storage Quota Exceeded**
**Unlikely but check:**
```javascript
// In console:
console.log(JSON.stringify(localStorage).length);
// Should be under 5MB (5,000,000 characters)
```

**Fix:** Clear old data or use a different browser

#### **4. JavaScript Error**
**Check Console (F12):**
- Look for red error messages
- Note the error and line number
- Report if you see errors

### **Debug Steps:**

**Step 1: Open Console**
```
F12 → Console tab
```

**Step 2: Try Adding Child**
```
Should see:
"Adding child: {name: ..., age: ...}"
"State after adding: [{...}]"
```

**Step 3: Check localStorage**
```javascript
// In console:
console.log(localStorage.getItem('dosed_children'));
// Should show JSON array with children
```

**Step 4: Manual Test**
```javascript
// Force save a child:
localStorage.setItem('dosed_children', JSON.stringify([
  {id: '123', name: 'Test Child', age: '5', weight: '20'}
]));
// Refresh page - should see Test Child
```

---

## ❌ Issue: QR Code Not Generating

### **Problem:**
Click "QR" button but no QR code appears

### **Causes:**

#### **1. QRCode.js Not Loaded**
**Check console for:** `QRCode is not defined`

**Fix:**
- Wait a few seconds and try again
- Check internet connection
- Hard refresh (Ctrl+Shift+R)

#### **2. Canvas Not Supported**
**Very old browsers only**

**Fix:** Use modern browser (Chrome, Safari, Firefox, Edge)

### **Workaround:**
Use "Share" button instead → WhatsApp text export

---

## ❌ Issue: Import Not Working

### **Problem:**
Clicking import link doesn't import data

### **Possible Causes:**

#### **1. Incomplete Link**
**Check:** Link should be very long (hundreds of characters)  
**Example:** `https://yoursite.com?import=eyJ2ZXJzaW9uIjoiOS...` (much longer)

**Fix:** Copy the entire link, don't truncate

#### **2. URL Encoding Issue**
**Some messaging apps** break long URLs

**Fix:**
1. Click "Import Data" button
2. Paste link manually
3. Click "Import from Link"

#### **3. Data Corrupted**
**Check console** for: `Import error: ...`

**Fix:** Ask sender to generate new QR/link

---

## ❌ Issue: Icons Not Showing

### **Problem:**
Buttons show emoji or text instead of icons

### **Status:** Working as Intended!

**Explanation:**
- If Lucide loads: Shows nice icons
- If Lucide fails: Shows emoji fallback
- **Both work perfectly**

**Emoji icons are the fallback:**
- 🌡️ = Thermometer
- 💊 = Medication
- 📋 = Records
- ➕ = Add
- 🗑️ = Delete

**Not a bug!** Just means Lucide CDN is slow/blocked.

---

## ❌ Issue: App Not Installing to Home Screen

### **Problem:**
Can't install as PWA / No install prompt

### **Fixes by Platform:**

#### **Android (Chrome):**
1. Visit site in Chrome (not other browsers)
2. Must be HTTPS (✓ GitHub Pages is)
3. Wait 3 seconds for auto-prompt
4. **Or:** Menu (⋮) → "Install app"
5. **Or:** Menu → "Add to Home screen"

**If still not working:**
- Clear Chrome cache
- Check Chrome is up to date
- Try incognito window first (then normal)

#### **iOS (Safari):**
**Must use Safari** (Chrome won't work on iOS for PWA)

1. Open in Safari
2. Tap Share button (□↗)
3. Scroll → "Add to Home Screen"
4. Tap "Add"

**If not appearing:**
- Check iOS version (needs 11.3+)
- Make sure using Safari, not Chrome
- Restart Safari

---

## ❌ Issue: Data Not Syncing Between Devices

### **This is Normal!**

**Dosed does NOT sync automatically.**

**Why:**
- Privacy by design
- Offline-first
- No cloud storage

**To share data between devices:**
1. Use "QR" button to share
2. Import on other device
3. Each device has its own copy

**Not a bug** - it's a privacy feature!

---

## ❌ Issue: WhatsApp Export Not Working

### **Problem:**
Click "Share" button, nothing happens

### **Fixes:**

#### **1. WhatsApp Not Installed**
**Desktop:** Goes to web.whatsapp.com (needs WhatsApp Web)  
**Mobile:** Opens WhatsApp app (must be installed)

**Fix:** Install WhatsApp or copy text manually

#### **2. Popup Blocked**
**Check:** Browser blocked popup

**Fix:**
- Allow popups for this site
- Look for popup blocked icon in address bar
- Click and allow

#### **3. iOS Restrictions**
**iOS sometimes blocks wa.me links**

**Workaround:**
1. Use "Copy Link" instead
2. Paste in WhatsApp manually

---

## ❌ Issue: Charts Not Showing

### **Problem:**
Click "Toggle Trends" but no charts appear

### **Causes:**

#### **1. Not Enough Data**
**Need:** At least 2 records with temperature

**Fix:** Add more records

#### **2. Chart.js Not Loaded**
**Check console:** `Chart is not defined`

**Fix:**
- Wait and try again
- Hard refresh (Ctrl+Shift+R)
- Check internet connection

---

## ❌ Issue: Service Worker Errors

### **Problem:**
Console shows: `Service worker registration failed`

### **Status:** Safe to Ignore!

**What it means:**
- Offline caching not available
- App still works fine
- Just won't work offline

**When this happens:**
- HTTP sites (need HTTPS)
- Localhost development
- Browser doesn't support SW

**Fix for production:**
- Use HTTPS (GitHub Pages ✓)
- Nothing else needed

---

## 🔍 General Debugging Steps

### **Always Start Here:**

1. **Open Console (F12)**
   - Look for red errors
   - Note error messages
   - Check for warnings

2. **Check Network Tab**
   - See if CDN resources loaded
   - Look for failed requests (red)

3. **Hard Refresh**
   - Ctrl+Shift+R (Windows/Linux)
   - Cmd+Shift+R (Mac)
   - Clears cache

4. **Try Incognito/Private**
   - Rules out extensions
   - Fresh localStorage
   - Clean state

5. **Test in Different Browser**
   - Chrome (best support)
   - Safari (iOS only)
   - Firefox (good)
   - Edge (good)

---

## 📱 Browser Compatibility

### **Fully Supported:**
- ✅ Chrome (Desktop & Android)
- ✅ Safari (Desktop & iOS)
- ✅ Edge (Desktop)
- ✅ Firefox (Desktop)

### **Limited Support:**
- ⚠️ Internet Explorer (don't use)
- ⚠️ Very old browsers (update)

### **Required Features:**
- localStorage
- ES6 JavaScript
- Fetch API
- Service Workers (optional)
- Canvas (for QR codes)

---

## 🆘 Getting More Help

### **If Issue Persists:**

1. **Check Console (F12)**
   - Copy full error message
   - Note which browser/version
   - Note which feature failing

2. **GitHub Issues:**
   - Go to: github.com/thegp-ie/Dosed/issues
   - Click "New Issue"
   - Provide:
     - Browser & version
     - Operating system
     - Error message
     - Steps to reproduce

3. **Quick Workarounds:**
   - Use different browser
   - Try on different device
   - Use WhatsApp export instead of QR
   - Manual data entry instead of import

---

## ✅ Quick Reference

| Problem | Quick Fix |
|---------|-----------|
| Lucide error | Ignore - emoji fallback works |
| Child not saving | Check incognito/privacy mode |
| QR not generating | Check internet, wait, retry |
| Import failing | Copy full link, paste manually |
| No install prompt | Menu → "Install app" |
| WhatsApp blocked | Copy text manually |
| Charts not showing | Need 2+ records |
| Icons as emoji | Normal fallback, works fine |

---

**Most issues are browser settings or slow CDN loads.**  
**The app has robust fallbacks and should work in most cases!** ✅

---

**Updated:** January 2026  
**Version:** 9.0 Ultimate
