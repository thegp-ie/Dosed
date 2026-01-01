# 🔄 Dosed Data Sharing Feature Guide

## 🆕 NEW FEATURES ADDED

### **1. QR Code Sharing**
Share child health data with family members via QR code

### **2. WhatsApp Link Sharing**
Send health data via WhatsApp message with import link

### **3. Data Import**
Receive and import health data from other users

---

## 🎯 **How It Works**

### **Sharing Data (Parent A → Parent B)**

1. **Parent A opens Dosed**
2. **Clicks "QR" button** on child's card
3. **Gets QR code** containing:
   - Child's profile (name, age, weight, allergies)
   - Last 50 health records
   - Active prescriptions
   - Export timestamp

4. **Shares via:**
   - **QR Code:** Parent B scans with phone camera
   - **WhatsApp:** Sends message with import link
   - **Copy Link:** Shares link via SMS/email

### **Importing Data (Parent B)**

**Method 1: Automatic (via link)**
1. Parent B clicks the share link
2. Dosed opens automatically
3. Confirms import
4. Data added to their app

**Method 2: Manual Import**
1. Parent B clicks "Import Data" button
2. Pastes share link
3. Clicks "Import"
4. Data added to their app

**Method 3: QR Scan**
1. Parent B uses phone camera
2. Scans QR code
3. Opens link
4. Data imported automatically

---

## 🔒 **Privacy & Security**

### **What's Shared:**
- ✅ Child's name, age, weight
- ✅ Medical conditions & allergies
- ✅ Last 50 health records (not all history)
- ✅ Active prescriptions
- ❌ NOT unlimited access
- ❌ NOT real-time sync
- ❌ Data at time of export only

### **How It Works:**
```
Parent A                    Parent B
   ↓                           ↓
Creates QR/Link          Scans/Clicks Link
   ↓                           ↓
Data → Base64           Link → Decode
   ↓                           ↓
Embedded in URL         Parse Data
   ↓                           ↓
Shared                  Import to Local Storage
```

### **Important Notes:**
- ✅ Data is **encoded in the URL** (not on a server)
- ✅ **One-time snapshot** (not live sync)
- ✅ Recipient gets **their own copy** (independent)
- ✅ Changes on Parent A's device **don't affect** Parent B
- ✅ Both can edit their own copies independently

---

## 📱 **Use Cases**

### **1. Co-Parenting**
**Scenario:** Mom has been tracking child's fever for 2 days, now Dad is taking over for the weekend.

**Solution:**
1. Mom clicks "QR" button
2. Sends WhatsApp message to Dad
3. Dad clicks link
4. Gets last 2 days of temperature records
5. Dad can continue tracking

### **2. Babysitter Handover**
**Scenario:** Parents need to share medication schedule with babysitter.

**Solution:**
1. Parent shares QR code
2. Babysitter scans with phone
3. Gets prescription details & dosing schedule
4. Can see when last dose was given

### **3. Doctor Visit**
**Scenario:** Taking child to GP/hospital.

**Solution:**
1. Generate QR code before appointment
2. Show doctor the QR (they can scan)
3. Or use regular "Share" button for text summary
4. Doctor gets complete health timeline

### **4. Grandparents**
**Scenario:** Child staying with grandparents for a week.

**Solution:**
1. Share health data via WhatsApp
2. Grandparents import into their Dosed app
3. They see allergies, medications, history
4. Can track and add new records

---

## 🎨 **User Interface**

### **On Child Cards:**
- **QR Button** (purple) - Opens QR sharing modal
- **Share Button** (blue) - WhatsApp text export

### **In Header:**
- **Import Data** (green) - Opens import modal

---

## 🔧 **Technical Details**

### **Data Format:**
```javascript
{
  version: '9.0',
  child: {
    id: 'abc123',
    name: 'Child Name',
    age: '5',
    weight: '20',
    allergies: ['Penicillin'],
    conditions: ['Asthma'],
    regularMedications: ['Ventolin']
  },
  records: [
    {
      id: 'rec1',
      timestamp: '2025-01-01T10:00:00.000Z',
      temperature: '38.5',
      medication: 'Calpol',
      dose: '7.5',
      unit: 'ml'
      // ... etc
    }
  ],
  prescriptions: [
    {
      id: 'presc1',
      medication: 'Amoxicillin',
      dose: '250',
      frequency: 'TDS',
      // ... etc
    }
  ],
  exportedAt: '2025-01-01T10:00:00.000Z'
}
```

### **Encoding:**
1. Convert to JSON string
2. Base64 encode
3. Add to URL: `?import=BASE64_DATA`

### **Decoding:**
1. Extract from URL parameter
2. Base64 decode
3. Parse JSON
4. Validate structure
5. Import with new IDs

### **ID Handling:**
- Original IDs are preserved in data
- New IDs generated on import to avoid conflicts
- Child name gets "(imported)" suffix
- User can rename after import

---

## ⚠️ **Limitations**

### **What This IS:**
- ✅ One-time data transfer
- ✅ Snapshot at time of export
- ✅ Complete copy for recipient
- ✅ Independent after import

### **What This IS NOT:**
- ❌ Real-time sync
- ❌ Live sharing
- ❌ Two-way updates
- ❌ Collaborative editing
- ❌ Cloud backup

### **Important:**
- If Parent A adds a record, Parent B **won't see it** (unless they share again)
- Both users maintain **independent copies**
- No ongoing connection after import

---

## 🚀 **Next Steps / Future Enhancements**

### **Potential Improvements:**

1. **Selective Sharing**
   - Choose which records to share
   - Date range selection
   - Specific data types only

2. **Merge Options**
   - Merge with existing child (not create new)
   - Conflict resolution
   - Duplicate detection

3. **Share Expiry**
   - Links expire after 24 hours
   - One-time use QR codes
   - Password protection

4. **Live Sync (Advanced)**
   - Optional cloud sync
   - Real-time updates
   - Requires backend service
   - Privacy considerations

5. **Share History**
   - Track what was shared
   - When and with whom
   - Revoke access (if live sync)

---

## 📊 **Comparison to WhatsApp Export**

| Feature | WhatsApp Export | QR/Link Share |
|---------|----------------|---------------|
| **Format** | Plain text | Importable data |
| **Import** | Manual copy/paste | One-click import |
| **Structure** | Human-readable | Machine-readable |
| **Use Case** | Read-only summary | Full data transfer |
| **Best For** | Doctors, reports | Family handover |

**Both are useful in different scenarios!**

---

## 🔍 **Testing the Feature**

### **Test Scenario 1: Same Device**
1. Add child with some records
2. Click "QR" button
3. Copy the share link
4. Open in new incognito window
5. Data should import
6. Check both versions are independent

### **Test Scenario 2: Two Devices**
1. **Phone A:** Create QR code
2. **Phone B:** Scan with camera
3. Opens link in browser
4. Imports automatically
5. Both have the data

### **Test Scenario 3: WhatsApp**
1. Click "QR" button
2. Choose "Share via WhatsApp"
3. Send to yourself
4. Click link in WhatsApp
5. Should open Dosed and import

---

## ✅ **Summary**

### **What Was Added:**
- 📷 QR code generation for data sharing
- 🔗 Shareable links with encoded data
- 💬 WhatsApp sharing integration
- 📥 Data import functionality
- 🔄 Automatic import from URLs
- 🆔 ID conflict resolution

### **Benefits:**
- ✅ Easy family data sharing
- ✅ No server/cloud needed
- ✅ Privacy maintained
- ✅ Works offline after import
- ✅ Complete data portability

### **Use Responsibly:**
- ⚠️ Only share with trusted people
- ⚠️ QR codes contain health data
- ⚠️ Anyone with link can import
- ⚠️ Consider privacy before sharing

---

**This feature makes Dosed perfect for co-parenting and family caregiving!** 🎉
