# ASTITVA demo test workflow (simple version)

Ab org mein sirf **5 log** hain:

| Role | Login | Kaam |
|---|---|---|
| Employee | `rahul.sharma@nexora.example` | Request daalta hai (Engineering) |
| Employee | `neha.gupta@nexora.example` | Request daalti hai (Finance) |
| Employee | `kavya.reddy@nexora.example` | Request daalti hai (HR) |
| **Manager** | `priya.desai@nexora.example` | Teeno employees ki manager. **Pehla approval** inka. |
| **Security Manager** | `admin@nexora.example` (Meera) | **Dusra / final approval** (security review). Alerts, emergency, audit, drift, AI agents, policies bhi yahi dekhti hai. |

**Password sabka:** `Nexora@Demo2026`

**OTP:** login page pe password daalne ke baad neeche **Dev mailbox** mein 6-digit code dikhta hai. Wahi daal do. Ab kisi ke liye authenticator app ki zaroorat nahi.

**Shortcut:** login page pe 5 buttons hain (Employee · Rahul, Manager · Priya, wagairah). Click karo, email apne aap bhar jayega.

**Ab flow risk score se decide hota hai:**

| Risk score | Kya hota hai |
|---|---|
| **0–30 (Low)** | Policy apne aap approve kar deti hai, **lekin sirf** jab resource sensitive na ho (INTERNAL) aur sirf READ/EXECUTE maanga ho. Priya ko FYI notification jaata hai. |
| **31–60 (Medium)** | Sirf Manager (Priya) ka approval. |
| **61–100 (High)** | Pehle Manager (Priya), phir Security Manager (Meera). |

**Human hamesha decide karega (score kitna bhi kam ho, ye kabhi auto-approve nahi hote, aur Meera bhi ye band nahi kar sakti):**
- **Sensitive model / dataset / database:** CONFIDENTIAL, RESTRICTED, CRITICAL. Sirf 2 INTERNAL engineering resources (Internal Analytics API, Development Database) auto ho sakte hain.
- **WRITE, DELETE, ADMIN** permission.
- **Unusual behaviour** (anomaly model ne flag kiya) to Security Manager ka review bhi zaroori.

- Request page pe stepper ke neeche **"Why this approval path"** likha aata hai, ki ye request is raste kyun gayi.
- Ye decision **backend ki rule-based policy** leti hai, AI model kabhi access grant nahi karta.
- 30 aur 60 wali limits Meera **Policies** page pe badal sakti hai. Guardrails wahan dikhte hain par band nahi hote.

**Naya: Deadline + Business impact (priority)**
- New request form mein **Needed by** (optional deadline) aur **Business impact** (Low / Medium / High / Critical) hai.
- Isse sirf **queue ka order** badalta hai (kaunsi request pehle dekhni hai). Risk score ya approval path kabhi nahi badalta.
- Formula: 40% deadline + 30% impact + 20% kitni der se wait + 10% urgency (Incident Response jaise purpose).
- Deadline nikal gayi to **Overdue** (laal), 24 ghante ke andar to **Due soon**.

> Saare paths maine browser mein UI se chala ke check kiye hain. **101 automated tests** pass hain.

## Test 0: Saare paths ek saath (sabse jaldi wala test)

`kavya.reddy` se login karo, **Access Requests → New request**, aur ye 4 requests daalo (duration 8 hours, sirf C mein 7 days):

| # | Resource | Purpose | Permissions | Justification | Mere test mein |
|---|---|---|---|---|---|
| A | Internal Analytics API | Analytics & Reporting | READ | Pull monthly headcount numbers for the HR leadership dashboard. | Risk 13 → **turant Auto-approved** |
| B | Customer Support AI Dataset | Model Performance Testing | READ | Check the HR helpdesk classifier against last quarter tickets before the release review. Needed by: aaj se ~10 ghante baad, Impact: High | Risk 43 → **sirf Priya** (CONFIDENTIAL hai, isliye auto nahi). Priority 37 Medium, "Due soon" |
| C | Fraud Detection Model | Model Training | READ + EXECUTE + WRITE | need it for hr work | Risk 87 → **Priya, phir Meera** |
| D | Development Database | Feature Development | READ + WRITE | Add the HR leave balance column to the development database for the Atlas sprint. | Risk 27 (low) par WRITE hai → **Priya ko approve karna padega** |

Kya check karna hai:
1. Request A kholo: "Auto-approved · By policy" aur neeche "Why this approval path".
2. Request B aur D kholo: "Why this approval path" mein likha hoga ki CONFIDENTIAL / WRITE ki wajah se human chahiye. B mein right side **Review priority** card dikhega.
3. `priya.desai` se login karo. **Notifications** mein A ka FYI. **Approval Center** mein B, C, D honge, A nahi. Upar filters (Overdue, Due in 24h, Critical…) aur **Sort by** try karo.
4. Priya B approve kare: B seedha **Approved**. Priya C approve kare: C ab Meera ke paas. `admin` se login karke approve karo.

**Tip:** do log ek saath dekhne ho to ek normal window aur ek Incognito window rakho. Ya upar right mein profile menu se Sign out karke dusre account se login karo.

---

## Test 1: Kavya → Fraud Detection Model (main test)

**Step 1: Kavya request daale**
1. `kavya.reddy` se login karo.
2. Sidebar mein **Access Requests** kholo, phir **New request** dabao.
3. Form aise bharo:
   - Resource: **Fraud Detection Model**
   - Purpose: **Model Performance Testing**
   - Duration: **24 hours**
   - Permissions: **READ + EXECUTE**
   - Justification: kuch bhi, 10+ characters
4. **Submit request** dabao. Request pending dikhegi. Fraud Detection Model CRITICAL hai, isliye auto-approve kabhi nahi hoga. Score 31–60 aaya to sirf Priya approve karegi (Step 3 ki zaroorat nahi), 60 se upar aaya to Priya ke baad Meera bhi.

**Step 2: Priya (Manager) approve kare**
1. `priya.desai` se login karo.
2. Upar bell icon mein notification aayega.
3. **Approval Center** kholo, phir tab **Needs my decision**. Kavya ki request wahan hogi.
4. Row pe click karo. Risk score aur AI ki recommendation dekho, phir **Approve** dabao. Stage ab "Security review" pe chala jayega.

**Step 3: Meera (Security Manager) approve kare**
1. `admin@nexora.example` se login karo.
2. **Approval Center** kholo, phir **Needs my decision**. Kavya ki request ab yahan aa gayi hogi.
3. **Approve** dabao. Status ab **Approved** ho jayega.

**Step 4: Kavya token use kare**
1. Wapas `kavya.reddy` se login karo.
2. **Active Access** kholo. Fraud Detection Model ka grant dikhega. Uske saamne **Token** dabao.
3. Neeche "Call the protected resource" box mein try karo:

| Action | Purpose | Result |
|---|---|---|
| READ | Model Performance Testing | ✅ **ALLOWED** |
| READ | Fraud Investigation | ❌ **TOKEN_PURPOSE_MISMATCH** |
| WRITE | Model Performance Testing | ❌ **PERMISSION_NOT_GRANTED** |

---

## Test 2: Dusre employees ke liye

| Employee | Resource | Purpose | Permissions |
|---|---|---|---|
| `neha.gupta` | Finance Ledger Database | Compliance Audit | READ |
| `rahul.sharma` | Internal Analytics API | Analytics & Reporting | READ |

Ye low risk hain, to zyada chance hai ki **apne aap approve** ho jaayein (Finance Ledger CRITICAL hai, wo hamesha Priya ke paas jaayega). Kitne log approve karenge ye score pe depend karta hai, upar wali table dekho.

---

## Test 3: Blocked cases (ye fail hone chahiye)

| Test | Kaise karo | Kya hona chahiye |
|---|---|---|
| **Order todna** | High-risk request (jaise Test 0 ki C) pe Meera seedha approve kare, Priya se pehle | ❌ "Only the requester's reporting manager can perform manager review." Request Meera ke queue mein Priya ke approve karne ke baad hi aati hai. |
| **Manager hi security approval de** | Priya approve karne ke baad security stage bhi khud approve karne ki koshish kare | ❌ Blocked. Security approval sirf Security Manager de sakti hai. Request Priya ke queue mein dobara aayegi hi nahi. |
| **Department block** | `kavya.reddy` (HR) **Finance Ledger Database** maange | ❌ Submit hi nahi hoga: "may only be accessed by FIN, SEC departments." |
| **Galat banda token use kare** | Rahul ke Active Access mein Product Recommendation Model ka token copy karo. Kavya ke Token dialog mein **Token override** field mein paste karke bhejo. | ❌ **TOKEN_IDENTITY_MISMATCH**, aur Meera ko HIGH alert jaata hai |
| **Security Manager khud request kare** | `admin` se Access Requests, phir New request | ❌ "No independent Security Manager is available to review your own request." Uske liye Emergency Access hai. |
| **Employee admin pages khole** | `rahul.sharma` se browser mein `/audit` ya `/policies` kholo | ❌ "You don't have access to this". Server 403 deta hai. |

---

## Test 4: Manager khud request kare

`priya.desai` se request daalo. Priya ke upar koi manager nahi hai, isliye request **seedha Meera** (Security Manager) ke paas jaati hai. Priya apni request khud approve nahi kar sakti.

---

## Test 5: Kisi employee ka access hatana

Ye **Meera** (kisi ka bhi) aur **Priya** (apni team ka) kar sakti hain. Employee khud apna access nahi hata sakta.

1. `priya.desai` se login karo, **Active Access** kholo, upar **My team** tab chuno. (Meera ke liye tab **Organisation** hai.)
2. Kavya ki **HR Employee Database** (READ + WRITE) wali row mein **Revoke** dabao.
3. **Sirf ek permission hatani ho:** WRITE pe click karo (laal ho jayega), reason likho, phir **Remove selected** dabao. READ chalta rahega, naya token ban jaata hai, purana token band ho jaata hai.
4. **Poora access hatana ho:** reason likho, phir **Revoke all access** dabao.
5. Ye request page se bhi ho sakta hai: request kholo, right side mein **Remove permissions / revoke** button hai.
6. `kavya.reddy` se login karo. Bell mein notification aayega. Access Requests list mein "Access revoked" dikhega, aur request page ke stepper mein laal "Access revoked · By Priya".

## Test 5b: Access Dependency Graph (model revoke karne se pehle impact dekho)

Sirf **Priya** (Manager) aur **Meera** (Security Manager) ko dikhta hai. Employee ko sidebar mein ye page nahi milega, aur API bhi 403 dega.

1. `admin` (Meera) se login karo, sidebar mein **Security → Dependency Graph** kholo. (Resource Registry mein kisi resource pe **Dependency graph** button se bhi aa sakte ho.)
2. Left list se **Fraud Detection Model** chuno. Graph mein dikhega:
   - **Directly affected:** jinke paas model ka access hai (users), AI agents, aur APIs jo model use karti hain (jaise Payments Fraud Scoring API).
   - **Indirectly affected:** Internal Analytics API ke users aur Developer AI Agent, kyunki wo API is model se data leti hai.
3. **Revoke access…** dabao. Users, AI agents aur API links tick karo. Confirm karne se pehle graph mein jo kuch band hoga wo laal blink karega, aur upar count dikhega (kitne users, tokens, agents, APIs, aur kitne indirectly degraded).
4. Chaho to graph mein nodes pe click karke sirf kuch chuno (checkbox).
5. Reason likho aur **Confirm revoke** dabao. Graph turant badlega: revoked user laal, API "Cut off", aur indirect wale "Degraded". **Before / After** toggle se dono compare karo.
6. Neeche **Reconnect** button se cut ki hui API wapas jod sakte ho. Agent ko wapas permission AI Security Center se milti hai.
7. `priya.desai` se same page kholo: sirf apni team ke log naam se dikhenge, baaki "N users in other teams" mein group honge. Priya sirf apni team ka access hata sakti hai, agents aur APIs nahi.

## Security Manager (Meera) aur kya dekh sakti hai

- **Overview:** pending requests, active access, alerts aur charts.
- **Audit & Compliance:**
  - Audit trail: har submit, approve, token use yahan log hota hai.
  - **Integrity** tab: "Verify chain" dabao, chain valid aani chahiye.
  - **Security alerts** tab.
- **Emergency Access:** Rahul ka ek live break-glass session chal raha hai. Use revoke ya review kar sakti ho.
- **Permission Drift:** 5 cases, jaise Rahul ke paas Dev DB pe extra DELETE/ADMIN. Revoke ya Restrict karke theek karo.
- **AI Security Center:** 4 AI agents.
- **Policies** aur **Settings → Users & roles**.

**Priya (Manager) ke paas:** Approval Center, Employee Intelligence (teeno employees ka kaam aur leaderboard), aur Access reviews (recertification).

**Pehli baar login karne pe** demo data mein har path ka example hai:
- REQ-2026-00031 (Rahul): auto-approved, risk 23 (INTERNAL, sirf READ)
- REQ-2026-00032 (Kavya): sirf Priya, risk 41 (RESTRICTED HR database + WRITE), deadline kal, "Due soon"
- REQ-2026-00033 (Rahul): Priya, phir Meera, risk 100, koi deadline nahi
- REQ-2026-00034 (Neha): Priya ne approve kar diya, ab Meera ke paas, risk 74, deadline nikal gayi, "Overdue"

**Limits badal ke dekhna ho:** `admin` se **Policies** kholo, upar "Risk-based approval routing" card mein numbers badlo (jaise 20 aur 50), **Save thresholds** dabao. Agli request se naye rules lagenge.

**Sab reset karna ho to (demo history ke saath):** `docker compose exec backend python -m app.seed --reset`

**Bilkul khaali start chahiye** (sirf 5 log, koi purana access / request / drift nahi):
- Docker: `docker compose exec backend python -m app.seed --reset --clean`
- Mac bina Docker: `./run-local.sh --clean`

Clean mode mein "Pehli baar login" wali demo requests (00031–00035) nahi hongi. Test 0 se shuru karo.

---

## Test 6: Priority queue (Overdue / Due soon)

1. `admin` (Meera) se login karo, **Approval Center** kholo.
2. Seed mein ek request (Neha, Fraud Detection Model) ki deadline nikal chuki hai: **Priority 62 High + Overdue** (laal). Kavya ki HR request "Due soon" hai.
3. **Overdue** filter dabao: sirf wahi dikhegi. **Sort by → Earliest deadline / Waiting longest** try karo.
4. Request kholo: right side **Review priority** card mein breakdown (Deadline +.., Impact +.., Waiting +..) aur reasons.
5. Requester (jaise Kavya) apni open request pe **Edit** dabake deadline/impact badal sakti hai. Ye audit mein jaata hai. Priority score koi khud set nahi kar sakta.

## Test 7: Alert confirm vs false positive

1. `admin` se login karo, **Audit & Compliance → Security alerts**.
2. Har open alert pe **Confirm** (asli violation, risk history mein count hoga) ya **False positive** (kabhi count nahi hoga).
3. Pehle denied request ya blocked call ko "violation" maana jaata tha. Ab sirf Confirm kiya hua alert violation hai.

## Risk engine mein kya badla (short)
- Reject hui request violation nahi maani jaati.
- Request ke **baad** ka koi event uske score mein use nahi hota.
- Current request khud velocity mein count nahi hoti, aur velocity person ke apne normal pace se compare hoti hai.
- Isolation Forest ko kam se kam 12 active log chahiye. Demo mein 5 hain, isliye risk factors mein **"Behaviour model: n/a, not enough data"** dikhta hai aur 0 points. Wo kuch fake result nahi deta.
