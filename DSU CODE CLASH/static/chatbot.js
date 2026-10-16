/* ============================================================
   SmartWaste AI Chatbot Engine — chatbot.js
   Drop into /static/ and include AFTER chatbot.css
   ============================================================

   USAGE — add to any dashboard template:
   ----------------------------------------
   <link rel="stylesheet" href="/static/chatbot.css">

   <!-- At end of <body>: -->
   <script>
     window.SW_CHATBOT_CONFIG = {
       role: 'resident',   // 'resident' | 'worker' | 'manager'
       userId: localStorage.getItem('uid') || null,
       workerId: localStorage.getItem('worker_id') || null,
       apiBase: '',        // e.g. '' for same origin
     };
   </script>
   <script src="/static/chatbot.js"></script>
   ============================================================ */

(function () {
  'use strict';

  /* ── Config ─────────────────────────────────────────────── */
  const CFG = window.SW_CHATBOT_CONFIG || {};
  const ROLE     = CFG.role    || _detectRole();
  const USER_ID  = CFG.userId  || localStorage.getItem('uid');
  const WORKER_ID= CFG.workerId|| localStorage.getItem('worker_id');
  const BASE     = (CFG.apiBase || '').replace(/\/$/, '');

  /* ── State ──────────────────────────────────────────────── */
  let isOpen       = false;
  let isListening  = false;
  let recognition  = null;
  let msgHistory   = [];   // [{role:'user'|'bot', text}]
  let unreadCount  = 0;

  /* ── Role detection from URL ─────────────────────────────── */
  function _detectRole() {
    const p = window.location.pathname;
    if (p.includes('worker'))  return 'worker';
    if (p.includes('manager')) return 'manager';
    if (p.includes('user'))    return 'resident';
    return 'unknown';
  }

  /* ── HTML Injection ─────────────────────────────────────── */
  function _inject() {
    const roleLabel   = { resident:'Resident', worker:'Field Worker', manager:'Manager', unknown:'Guest' }[ROLE];
    const roleCls     = ROLE;

    document.body.insertAdjacentHTML('beforeend', `
    <!-- SmartWaste Chatbot -->
    <button id="sw-chat-bubble" aria-label="Open SmartWaste AI Chat">
      <span id="sw-notif-badge"></span>
      <span class="sw-bubble-icon-open">
        <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 10H6V10h12v2zm0-3H6V7h12v2z"/></svg>
      </span>
      <span class="sw-bubble-icon-close" style="display:none">
        <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </span>
    </button>

    <div id="sw-chat-panel" role="dialog" aria-label="SmartWaste AI Assistant">

      <!-- Header -->
      <div id="sw-panel-header">
        <div class="sw-header-avatar">
          <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
        </div>
        <div class="sw-header-info">
          <div class="sw-header-title">SmartWaste AI</div>
          <div class="sw-header-subtitle">
            <span class="sw-status-dot"></span>
            Online &nbsp;·&nbsp; <span class="sw-role-badge ${roleCls}">${roleLabel}</span>
          </div>
        </div>
        <div class="sw-header-actions">
          <button class="sw-header-btn" id="sw-clear-btn" title="Clear chat">
            <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      </div>

      <!-- Role switcher (only if unknown/landing page) -->
      <div id="sw-role-bar" ${ROLE !== 'unknown' ? 'style="display:none"' : ''}>
        <button class="sw-role-btn ${ROLE==='resident'?'active':''}" data-role="resident">🏠 Resident</button>
        <button class="sw-role-btn ${ROLE==='worker'?'active':''}"   data-role="worker">👷 Worker</button>
        <button class="sw-role-btn ${ROLE==='manager'?'active':''}"  data-role="manager">📊 Manager</button>
      </div>

      <!-- Messages -->
      <div id="sw-messages">
        <div class="sw-date-sep">Today</div>
        <div class="sw-msg-row bot" id="sw-welcome-row">
          <div class="sw-msg-avatar">🤖</div>
          <div class="sw-bubble" id="sw-welcome-msg"></div>
        </div>
        <!-- Typing indicator (hidden) -->
        <div id="sw-typing">
          <div class="sw-msg-avatar">🤖</div>
          <div class="sw-typing-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>

      <!-- Quick actions -->
      <div id="sw-quick-actions"></div>

      <!-- Input -->
      <div id="sw-input-area">
        <textarea id="sw-input" rows="1" placeholder="Ask me anything…" maxlength="500"></textarea>
        <button id="sw-voice-btn" title="Voice input">
          <svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15c-.08-.49-.49-.85-.98-.85-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z"/></svg>
        </button>
        <button id="sw-send-btn" title="Send">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>

    </div>
    `);
  }

  /* ── Welcome Message ─────────────────────────────────────── */
  const WELCOME = {
    resident: `👋 Hi there! I'm your <strong>SmartWaste AI</strong> assistant.<br><br>I can help you:<br>• 🗺️ Track your garbage truck live<br>• 📸 Report illegal dump spots<br>• 📋 File missed-collection complaints<br>• ♻️ Learn waste segregation rules<br>• 🔔 Check notifications<br><br>What can I help you with today?`,
    worker:   `👷 Welcome, Field Worker! I'm your <strong>SmartWaste AI</strong> companion.<br><br>I can help you:<br>• 📍 Check your area assignment & residents<br>• 🗺️ View blackspots on your route<br>• 📸 Upload cleaning proof photos<br>• 🌡️ Safety tips & PPE guidelines<br>• ⏰ Optimal schedule analysis<br><br>Stay safe out there! What do you need?`,
    manager:  `📊 Hello, Manager! Your <strong>SmartWaste AI</strong> command center is ready.<br><br>I can provide:<br>• 📈 Live system analytics & stats<br>• 👷 Worker status & GPS coverage<br>• 🗑️ Blackspot report summaries<br>• ✅ Complaint verification insights<br>• ⏰ Best pickup time analysis<br><br>Ask me anything about your operations!`,
    unknown:  `🌱 Welcome to <strong>SmartWaste AI</strong>!<br><br>I'm your intelligent waste management assistant. Select your role above or just ask me a question — I'll figure out how to help you!`,
  };

  const QUICK_CHIPS = {
    resident: ['🚛 Where is my truck?','♻️ Segregation guide','📸 Report dump spot','📋 File complaint','🔔 My notifications','📍 My area worker'],
    worker:   ['📋 My assignment','🗑️ Blackspots on route','⏰ Best collection time','📸 Upload proof','🛡️ Safety tips','🗺️ Open coverage map'],
    manager:  ['📊 System stats','👷 Worker status','🗑️ Pending blackspots','📈 Analytics','📋 Complaints overview','⏰ Best pickup time'],
    unknown:  ['🏠 I\'m a resident','👷 I\'m a worker','📊 I\'m a manager','♻️ Waste tips'],
  };

  /* ── Knowledge Base ──────────────────────────────────────── */
  const KB = {
    segregation: `♻️ <strong>Bangalore Waste Segregation (BBMP Rules)</strong><br><br>
<strong>🟢 Green Bin — Wet / Organic</strong><br>
Food scraps, vegetable peels, fruit waste, tea leaves, eggshells, garden trimmings, cooked food leftovers<br><br>
<strong>🔵 Blue Bin — Dry / Recyclable</strong><br>
Paper, cardboard, glass bottles, plastic bottles (clean), metals, cartons, e-waste (some centres)<br><br>
<strong>🔴 Red Bin — Reject / Hazardous</strong><br>
Sanitary napkins, diapers, medical waste, broken glass, tissue paper, thermocol, multilayer plastic<br><br>
<strong>💡 Tips:</strong> Rinse containers before binning. Avoid mixing wet + dry. Composting wet waste earns BBMP rebates!`,

    composting: `🌱 <strong>Home Composting Guide</strong><br><br>
<strong>What to compost:</strong> Vegetable peels, fruit waste, garden leaves, coffee grounds, tea bags<br>
<strong>What NOT to compost:</strong> Meat, dairy, oily food, diseased plants<br><br>
<strong>Process:</strong><br>
1. Layer: browns (dry leaves) + greens (food scraps) alternately<br>
2. Keep moist — not wet<br>
3. Turn every 3-4 days for aeration<br>
4. Ready in 30-60 days (dark, crumbly, earthy smell)<br><br>
<strong>BBMP Benefit:</strong> Registered composters get ₹500/month discount on property tax! 🎉`,

    bbmp: `🏛️ <strong>BBMP Waste Rules for Bangalore</strong><br><br>
• Mandatory source segregation (wet + dry + reject bins)<br>
• Penalty: ₹500-₹5,000 for throwing on streets<br>
• Bulk generators (>50 kg/day) must process on-site<br>
• Plastic below 75 microns is banned<br>
• Timings: Collection between 6AM-10AM in most zones<br>
• Complaint: BBMP helpline <strong>1533</strong> or <em>BBMP Sahaaya app</em><br><br>
Use SmartWaste to file digital complaints with GPS proof! 📍`,

    safety: `🛡️ <strong>Worker Safety Guidelines</strong><br><br>
<strong>Essential PPE:</strong><br>
• Gloves (heavy-duty rubber) — mandatory<br>
• Closed-toe boots / steel-toe shoes<br>
• Reflective vest / safety jacket<br>
• Face mask (N95 for hazardous areas)<br><br>
<strong>Heat Safety (Bangalore summers):</strong><br>
• Drink 250ml water every 30 minutes<br>
• Avoid direct sun 12PM-3PM where possible<br>
• Report heat stroke symptoms immediately: dizziness, dry skin, confusion<br><br>
<strong>Hazardous Waste Protocol:</strong><br>
• Medical/chemical waste → DO NOT touch → call supervisor<br>
• Needle / sharps → use tongs, seal in rigid container<br>
• Report to manager via app immediately`,

    schedule: `⏰ <strong>Collection Schedule System</strong><br><br>
SmartWaste uses <strong>resident time-preference voting</strong> to find the optimal pickup window:<br><br>
1. Each resident registers their preferred collection time<br>
2. System aggregates preferences in 30-minute buckets<br>
3. Majority-vote algorithm finds the single best time per area<br>
4. Workers see the optimal time in their Schedule tab<br><br>
To update your preferred time → <em>My Area tab</em> → Time Preference.<br>
The more residents who vote, the more accurate the schedule!`,

    navigation: {
      resident: {
        'map':        'Go to the <strong>Map tab</strong> in your dashboard to see live truck GPS, your house pin, and the truck\'s trail.',
        'truck':      'Go to the <strong>Map tab</strong> — the truck icon shows real-time position, updating every 5 seconds.',
        'complaint':  'Go to the <strong>Inform tab</strong> to file a complaint if your truck didn\'t come. Your GPS is auto-recorded.',
        'blackspot':  'Go to the <strong>Upload tab</strong> to report an illegal dump spot with a photo.',
        'spots':      'Go to the <strong>Spots tab</strong> to see all reported garbage spots and their cleaning status.',
        'area':       'Go to the <strong>My Area tab</strong> to see your assigned worker, scheduled time, and zone coverage.',
        'notification':'Go to the <strong>My Area tab</strong> — notifications appear there when your truck is within 400m.',
      },
      worker: {
        'area':       'Open the <strong>Area tab</strong> to see your assigned zone, resident list, and coverage progress.',
        'blackspot':  'Open the <strong>Map tab</strong> — red pins show blackspots you need to clean on your route.',
        'proof':      'Open the <strong>Proof tab</strong> to upload your "after cleaning" photo linked to a blackspot report.',
        'schedule':   'Open the <strong>Schedule tab</strong> to see the optimal collection time calculated from resident preferences.',
        'map':        'Open the <strong>Map tab</strong> — your live GPS trail shows in green as you move.',
      },
      manager: {
        'worker':     'Open the <strong>Workers panel</strong> to see all registered workers, their online status, and GPS positions.',
        'blackspot':  'Open the <strong>Spots panel</strong> to view all reported dump sites, dispatch workers, and track cleaning.',
        'analytics':  'Open the <strong>Analytics panel</strong> for charts on resident time preferences and system-wide stats.',
        'coverage':   'Open the <strong>Coverage Map panel</strong> to see live worker GPS trails and area assignments.',
        'complaint':  'Open the <strong>Complaints panel</strong> to view all citizen complaints with auto-verification status.',
        'assign':     'In the <strong>Workers panel</strong>, click "Assign Area", draw a polygon on the map, and set time.',
      }
    }
  };

  /* ── Intent Detection ────────────────────────────────────── */
  function _detectIntent(text) {
    const t = text.toLowerCase();
    // Navigation
    if (/truck|location|gps|where.*truck|live.*truck/.test(t))          return 'nav_truck';
    if (/complaint|missed|didn.t come|not.*come/.test(t))               return 'nav_complaint';
    if (/blackspot|illegal|dump|garbage.*spot|report.*spot/.test(t))    return 'nav_blackspot';
    if (/spot.*status|cleaned.*spot|see.*spots/.test(t))                return 'nav_spots';
    if (/area|zone|my.*worker|assigned|assignment/.test(t))             return 'nav_area';
    if (/notification|alert|proximity|near|coming/.test(t))             return 'nav_notification';
    if (/proof|after.*photo|clean.*photo/.test(t))                      return 'nav_proof';
    if (/schedule|time|best.*time|optimal/.test(t))                     return 'nav_schedule';
    if (/map|trail|path|route|coverage/.test(t))                        return 'nav_map';
    if (/analytic|stat|data|chart|insight/.test(t))                     return 'nav_analytics';
    // Data queries
    if (/how many.*worker|worker.*count|total.*worker/.test(t))         return 'data_workers';
    if (/how many.*blackspot|pending.*spot|spot.*count/.test(t))        return 'data_blackspots';
    if (/how many.*complaint|complaint.*count/.test(t))                 return 'data_complaints';
    if (/stats|dashboard.*data|overview|summary/.test(t))               return 'data_summary';
    if (/best.*pickup|pickup.*time|optimal.*time/.test(t))              return 'data_time';
    // Knowledge
    if (/segregat|which.*bin|bin.*which|wet.*dry|what.*bin/.test(t))   return 'kb_segregation';
    if (/compost|home.*compost|organic.*compost/.test(t))               return 'kb_composting';
    if (/bbmp|rule|law|bylaw|penalt|fine/.test(t))                      return 'kb_bbmp';
    if (/safety|ppe|protect|heat|hazard|injur/.test(t))                 return 'kb_safety';
    if (/schedule.*work|how.*schedule|time.*preferenc/.test(t))         return 'kb_schedule';
    // Greetings
    if (/^(hi|hello|hey|namaste|good morning|good afternoon|sup|yo)/.test(t)) return 'greeting';
    if (/help|what can you|what do you|how can/.test(t))                return 'help';
    if (/thank|thanks|thx|ty/.test(t))                                  return 'thanks';
    return 'ai';
  }

  /* ── Response Builder ────────────────────────────────────── */
  async function _buildResponse(userText) {
    const intent = _detectIntent(userText);

    switch (intent) {
      case 'greeting':
        return _greeting();
      case 'help':
        return _helpMsg();
      case 'thanks':
        return `You're welcome! 😊 If you need anything else — waste tips, truck tracking, complaints — just ask!`;

      case 'kb_segregation':
        return KB.segregation;
      case 'kb_composting':
        return KB.composting;
      case 'kb_bbmp':
        return KB.bbmp;
      case 'kb_safety':
        return KB.safety;
      case 'kb_schedule':
        return KB.schedule;

      case 'nav_truck':
        return _navGuide('truck') || `Open the <strong>Map tab</strong> to see the live truck GPS. It updates every 5 seconds! 🚛`;
      case 'nav_complaint':
        return _navGuide('complaint') || `Go to the <strong>Inform tab</strong> to file a complaint. Your GPS location is automatically attached.`;
      case 'nav_blackspot':
        return _navGuide('blackspot') || `Go to the <strong>Upload tab</strong> to report an illegal dump with a photo. 📸`;
      case 'nav_spots':
        return _navGuide('spots') || `Open the <strong>Spots tab</strong> to see all reported dump spots and their status.`;
      case 'nav_area':
        return _navGuide('area') || `Open the <strong>Area tab</strong> to see your zone and coverage details.`;
      case 'nav_notification':
        return _navGuide('notification') || `Notifications appear when the truck is within 400m of your location. Check your <strong>My Area tab</strong>.`;
      case 'nav_proof':
        return _navGuide('proof') || `Open the <strong>Proof tab</strong> to upload your cleaning photo.`;
      case 'nav_schedule':
        return _navGuide('schedule') || `Open the <strong>Schedule tab</strong> for the AI-optimized pickup time.`;
      case 'nav_map':
        return _navGuide('map') || `Open the <strong>Map tab</strong> for the live GPS coverage view.`;
      case 'nav_analytics':
        return _navGuide('analytics') || `Open the <strong>Analytics panel</strong> for charts and insights.`;

      case 'data_workers':
        return await _fetchWorkerStats();
      case 'data_blackspots':
        return await _fetchBlackspotStats();
      case 'data_complaints':
        return await _fetchComplaintStats();
      case 'data_summary':
        return await _fetchSummary();
      case 'data_time':
        return await _fetchTimeAnalysis();

      case 'ai':
      default:
        return await _callGemini(userText);
    }
  }

  /* ── Navigation Helper ──────────────────────────────────── */
  function _navGuide(key) {
    const navMap = KB.navigation[ROLE] || {};
    if (navMap[key]) {
      return navMap[key] + `<br><br><em>Tip: Look for the tab in your dashboard menu above.</em>`;
    }
    return null;
  }

  /* ── Greeting ────────────────────────────────────────────── */
  function _greeting() {
    const hour = new Date().getHours();
    const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
    const msgs = [
      `${greet}! 👋 I'm SmartWaste AI. How can I help you today?`,
      `${greet}! 🌱 Ready to help with anything waste management. Ask away!`,
      `${greet}! ♻️ SmartWaste AI at your service. What do you need?`,
    ];
    return msgs[Math.floor(Math.random() * msgs.length)];
  }

  /* ── Help ────────────────────────────────────────────────── */
  function _helpMsg() {
    const roleHelp = {
      resident: `I can help you with:<br>• 🚛 Track your truck live<br>• 📸 Report dump spots<br>• 📋 File complaints<br>• ♻️ Waste segregation guide<br>• 🏛️ BBMP rules & fines<br>• 🌱 Composting tips<br><br>Just type your question or use the quick buttons below!`,
      worker:   `I can help you with:<br>• 📋 Your area assignment<br>• 🗑️ Blackspots on your route<br>• 📸 Cleaning proof upload<br>• ⏰ Optimal schedule info<br>• 🛡️ Safety & PPE tips<br>• 🗺️ Coverage map navigation<br><br>Stay safe and ask away! 💪`,
      manager:  `I can provide:<br>• 📈 Live system analytics<br>• 👷 Worker status & GPS data<br>• 🗑️ Blackspot report summaries<br>• ✅ Complaint verification data<br>• ⏰ Best pickup time analysis<br>• 🗺️ Coverage insights<br><br>Ask me for any operational data!`,
      unknown:  `I can help with waste management info, guide you to the right dashboard, or answer questions about the SmartWaste system. Select your role for more specific help!`,
    };
    return roleHelp[ROLE] || roleHelp.unknown;
  }

  /* ── Live Data Fetches ───────────────────────────────────── */
  async function _fetchWorkerStats() {
    try {
      const res = await fetch(`${BASE}/api/manager/workers`);
      const data = await res.json();
      const workers = data.workers || [];
      const online  = workers.filter(w => w.online).length;
      const offline = workers.length - online;
      return `👷 <strong>Worker Status</strong>
<div class="sw-data-card">
  <div class="sw-stat-row"><span class="sw-stat-label">Total Workers</span><span class="sw-stat-value">${workers.length}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">🟢 Online Now</span><span class="sw-stat-value">${online}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">⚫ Offline</span><span class="sw-stat-value">${offline}</span></div>
</div>
<br><em>Open <strong>Workers panel</strong> to see each worker's live position and assign areas.</em>`;
    } catch (e) {
      return `⚠️ Couldn't fetch worker data right now. Make sure the Flask server is running and check the <strong>Workers panel</strong> directly.`;
    }
  }

  async function _fetchBlackspotStats() {
    try {
      const res = await fetch(`${BASE}/api/manager/blackspots`);
      const data = await res.json();
      const spots = data.blackspots || [];
      const pending    = spots.filter(s => !s.assigned_worker_id).length;
      const dispatched = spots.filter(s => s.assigned_worker_id && !s.cleaned).length;
      const cleaned    = spots.filter(s => s.cleaned).length;
      return `🗑️ <strong>Blackspot Reports</strong>
<div class="sw-data-card">
  <div class="sw-stat-row"><span class="sw-stat-label">Total Reported</span><span class="sw-stat-value">${spots.length}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">🔴 Pending Action</span><span class="sw-stat-value">${pending}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">🟡 Dispatched</span><span class="sw-stat-value">${dispatched}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">✅ Cleaned</span><span class="sw-stat-value">${cleaned}</span></div>
</div>
${spots.length > 0 ? `<div class="sw-progress-wrap"><div class="sw-progress-label"><span>Cleaning Progress</span><span>${Math.round(cleaned/spots.length*100)}%</span></div><div class="sw-progress-bar"><div class="sw-progress-fill" style="width:${Math.round(cleaned/spots.length*100)}%"></div></div></div>` : ''}`;
    } catch (e) {
      return `⚠️ Couldn't fetch blackspot data. Check the <strong>Spots panel</strong> directly.`;
    }
  }

  async function _fetchComplaintStats() {
    try {
      const res = await fetch(`${BASE}/api/manager/complaints`);
      const data = await res.json();
      const complaints = data.complaints || [];
      const visited    = complaints.filter(c => c.verified_status === 'Truck Visited').length;
      const notVisited = complaints.filter(c => c.verified_status === 'Truck Did Not Visit').length;
      const pending    = complaints.filter(c => !c.verified_status).length;
      return `📋 <strong>Complaint Overview</strong>
<div class="sw-data-card">
  <div class="sw-stat-row"><span class="sw-stat-label">Total Complaints</span><span class="sw-stat-value">${complaints.length}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">✅ Truck Did Visit</span><span class="sw-stat-value">${visited}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">❌ Truck Missed</span><span class="sw-stat-value">${notVisited}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">⏳ Unverified</span><span class="sw-stat-value">${pending}</span></div>
</div>
<br><em>Open the <strong>Complaints panel</strong> to see GPS-auto-verified details.</em>`;
    } catch (e) {
      return `⚠️ Couldn't fetch complaints data. Check the <strong>Complaints panel</strong> directly.`;
    }
  }

  async function _fetchTimeAnalysis() {
    try {
      const res = await fetch(`${BASE}/api/manager/time_analysis`);
      const data = await res.json();
      const best = data.best_time || 'Not enough data yet';
      const total = data.total_votes || 0;
      return `⏰ <strong>Best Collection Time Analysis</strong>
<div class="sw-data-card">
  <div class="sw-stat-row"><span class="sw-stat-label">Optimal Pickup Time</span><span class="sw-stat-value">🏆 ${best}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">Resident Votes</span><span class="sw-stat-value">${total}</span></div>
</div>
<br><em>Based on majority-vote across all resident time preferences. Open <strong>Analytics panel</strong> for the full bar chart.</em>`;
    } catch (e) {
      return `⚠️ Couldn't fetch time analysis. Open the <strong>Analytics panel</strong> for full data.`;
    }
  }

  async function _fetchSummary() {
    try {
      const [wRes, bRes, cRes] = await Promise.all([
        fetch(`${BASE}/api/manager/workers`).then(r => r.json()).catch(() => ({})),
        fetch(`${BASE}/api/manager/blackspots`).then(r => r.json()).catch(() => ({})),
        fetch(`${BASE}/api/manager/complaints`).then(r => r.json()).catch(() => ({})),
      ]);
      const workers    = (wRes.workers || []).length;
      const online     = (wRes.workers || []).filter(w => w.online).length;
      const spots      = (bRes.blackspots || []).length;
      const cleaned    = (bRes.blackspots || []).filter(s => s.cleaned).length;
      const complaints = (cRes.complaints || []).length;
      const missed     = (cRes.complaints || []).filter(c => c.verified_status === 'Truck Did Not Visit').length;

      return `📊 <strong>SmartWaste System Summary</strong>
<div class="sw-data-card">
  <div class="sw-stat-row"><span class="sw-stat-label">👷 Total Workers</span><span class="sw-stat-value">${workers} (${online} online)</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">🗑️ Blackspots</span><span class="sw-stat-value">${spots} total</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">✅ Spots Cleaned</span><span class="sw-stat-value">${cleaned}/${spots}</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">📋 Complaints</span><span class="sw-stat-value">${complaints} filed</span></div>
  <div class="sw-stat-row"><span class="sw-stat-label">❌ Missed Pickups</span><span class="sw-stat-value">${missed} confirmed</span></div>
</div>
${spots > 0 ? `<div class="sw-progress-wrap"><div class="sw-progress-label"><span>Overall Cleaning Rate</span><span>${Math.round(cleaned/spots*100)}%</span></div><div class="sw-progress-bar"><div class="sw-progress-fill" style="width:${Math.round(cleaned/spots*100)}%"></div></div></div>` : ''}`;
    } catch (e) {
      return `⚠️ Couldn't load full summary. Check each panel directly in your manager dashboard.`;
    }
  }

  /* ── Gemini AI Fallback ──────────────────────────────────── */
  async function _callGemini(userText) {
    // Build context for Gemini
    const history = msgHistory.slice(-6).map(m => ({
      role: m.role === 'bot' ? 'model' : 'user',
      text: m.text.replace(/<[^>]*>/g, '') // strip HTML tags for context
    }));

    const contextPrompt = `You are SmartWaste AI, an intelligent assistant for a municipal waste management platform called SmartWaste in Bangalore, India. 
The user is a ${ROLE}. 
SmartWaste features: GPS truck tracking, blackspot reporting, complaint filing, worker area assignment (polygon on map), AI complaint verification, time-preference analytics.
The platform has three dashboards: Resident (track truck, report spots, file complaints), Worker (view assigned area, upload cleaning proof, GPS tracking), Manager (monitor workers, dispatch to spots, analytics, coverage map).
Be helpful, concise, and always relate answers to waste management in Bangalore. Keep responses under 150 words. Use simple HTML for formatting (strong, br tags only, no markdown).
Answer in a friendly, conversational tone. If asked about navigation, guide them to the right tab/panel.`;

    try {
      const payload = {
        message: userText,
        role: ROLE,
        context: contextPrompt,
        history: history
      };
      const res = await fetch(`${BASE}/api/chatbot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      return data.reply || data.response || data.message || `I'm not sure about that. Try asking about waste segregation, truck tracking, or system features!`;
    } catch (e) {
      return _localFallback(userText);
    }
  }

  /* ── Local Fallback (when server is down) ────────────────── */
  function _localFallback(text) {
    const t = text.toLowerCase();
    if (/plastic/.test(t))     return `♻️ Plastic bottles → <strong>Blue Bin (dry/recyclable)</strong>. Rinse before disposing. Plastic bags below 75 microns are banned in Bangalore!`;
    if (/food|kitchen|leftov/.test(t)) return `🟢 Kitchen food waste → <strong>Green Bin (wet/organic)</strong>. Consider home composting — BBMP offers tax rebates for registered composters!`;
    if (/paper|card/.test(t))  return `📦 Paper & cardboard → <strong>Blue Bin (dry/recyclable)</strong>. Ensure they are dry and not soiled.`;
    if (/glass/.test(t))       return `🍶 Glass bottles → <strong>Blue Bin (dry/recyclable)</strong>. Wrap broken glass in newspaper before placing in bin.`;
    if (/battery|electric/.test(t)) return `⚡ Batteries & e-waste → <strong>Nearest BBMP e-waste collection point</strong>. Do NOT put in regular bins — they contain hazardous chemicals.`;
    if (/medical|needle|syringe/.test(t)) return `⚠️ Medical waste → <strong>Red Bin (hazardous/reject)</strong>. Workers should NOT handle syringes/needles with bare hands. Use tongs and rigid container.`;
    return `🤔 Great question! I'm working on a detailed answer. For now, check BBMP's waste guidelines or ask about: ♻️ segregation, 🌱 composting, 🏛️ BBMP rules, 🚛 truck tracking, or 📋 complaints!`;
  }

  /* ── DOM Helpers ────────────────────────────────────────── */
  function _addMsg(role, html) {
    const msgs = document.getElementById('sw-messages');
    const typingEl = document.getElementById('sw-typing');

    const row = document.createElement('div');
    row.className = `sw-msg-row ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'sw-msg-avatar';
    avatar.textContent = role === 'bot' ? '🤖' : '👤';

    const bubble = document.createElement('div');
    bubble.className = 'sw-bubble';
    bubble.innerHTML = html;

    row.appendChild(avatar);
    row.appendChild(bubble);

    msgs.insertBefore(row, typingEl);
    _scrollToBottom();

    // Store in history
    msgHistory.push({ role, text: html });

    // Badge if closed
    if (!isOpen && role === 'bot') {
      unreadCount++;
      const badge = document.getElementById('sw-notif-badge');
      badge.textContent = unreadCount;
      badge.classList.add('show');
    }
  }

  function _showTyping(show) {
    document.getElementById('sw-typing').classList.toggle('show', show);
    _scrollToBottom();
  }

  function _scrollToBottom() {
    const msgs = document.getElementById('sw-messages');
    msgs.scrollTop = msgs.scrollHeight;
  }

  /* ── Send Message ───────────────────────────────────────── */
  async function _send(text) {
    text = text.trim();
    if (!text) return;

    const input = document.getElementById('sw-input');
    input.value = '';
    input.style.height = 'auto';

    _addMsg('user', text);
    _showTyping(true);

    // Small delay for realism
    await _sleep(300 + Math.random() * 400);

    try {
      const reply = await _buildResponse(text);
      _showTyping(false);
      _addMsg('bot', reply);
    } catch (e) {
      _showTyping(false);
      _addMsg('bot', `⚠️ Something went wrong. Please try again or check your connection.`);
    }
  }

  function _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  /* ── Toggle Panel ───────────────────────────────────────── */
  function _toggle() {
    isOpen = !isOpen;
    const bubble = document.getElementById('sw-chat-bubble');
    const panel  = document.getElementById('sw-chat-panel');

    bubble.classList.toggle('open', isOpen);
    panel.classList.toggle('open', isOpen);

    if (isOpen) {
      // Reset unread badge
      unreadCount = 0;
      const badge = document.getElementById('sw-notif-badge');
      badge.textContent = '';
      badge.classList.remove('show');

      setTimeout(() => {
        document.getElementById('sw-input').focus();
        _scrollToBottom();
      }, 350);
    }
  }

  /* ── Voice Input ────────────────────────────────────────── */
  function _initVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      document.getElementById('sw-voice-btn').style.display = 'none';
      return;
    }
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-IN';

    recognition.onstart = () => {
      isListening = true;
      document.getElementById('sw-voice-btn').classList.add('listening');
      document.getElementById('sw-input').placeholder = '🎤 Listening…';
    };

    recognition.onresult = (e) => {
      const transcript = Array.from(e.results).map(r => r[0].transcript).join('');
      document.getElementById('sw-input').value = transcript;
    };

    recognition.onend = () => {
      isListening = false;
      document.getElementById('sw-voice-btn').classList.remove('listening');
      document.getElementById('sw-input').placeholder = 'Ask me anything…';
      const val = document.getElementById('sw-input').value.trim();
      if (val) _send(val);
    };

    recognition.onerror = () => {
      isListening = false;
      document.getElementById('sw-voice-btn').classList.remove('listening');
      document.getElementById('sw-input').placeholder = 'Ask me anything…';
    };
  }

  /* ── Role Switcher ──────────────────────────────────────── */
  function _setRole(role) {
    document.querySelectorAll('.sw-role-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.role === role);
    });
    // Update welcome message
    document.getElementById('sw-welcome-msg').innerHTML = WELCOME[role] || WELCOME.unknown;
    // Update chips
    _renderChips(role);
    window._SW_ACTIVE_ROLE = role;
  }

  /* ── Quick Action Chips ─────────────────────────────────── */
  function _renderChips(role) {
    const chips = QUICK_CHIPS[role] || QUICK_CHIPS.unknown;
    const container = document.getElementById('sw-quick-actions');
    container.innerHTML = chips.map(c =>
      `<button class="sw-chip" data-query="${c.replace(/"/g,"'")}">${c}</button>`
    ).join('');

    container.querySelectorAll('.sw-chip').forEach(btn => {
      btn.addEventListener('click', () => _send(btn.dataset.query));
    });
  }

  /* ── Auto-grow textarea ─────────────────────────────────── */
  function _autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 100) + 'px';
  }

  /* ── Init ───────────────────────────────────────────────── */
  function init() {
    _inject();

    // Set welcome message
    document.getElementById('sw-welcome-msg').innerHTML = WELCOME[ROLE] || WELCOME.unknown;

    // Render chips
    _renderChips(ROLE);

    // Init voice
    _initVoice();

    // Events
    document.getElementById('sw-chat-bubble').addEventListener('click', _toggle);

    document.getElementById('sw-send-btn').addEventListener('click', () => {
      _send(document.getElementById('sw-input').value);
    });

    document.getElementById('sw-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        _send(document.getElementById('sw-input').value);
      }
    });

    document.getElementById('sw-input').addEventListener('input', function() {
      _autoGrow(this);
    });

    document.getElementById('sw-voice-btn').addEventListener('click', () => {
      if (!recognition) return;
      if (isListening) { recognition.stop(); }
      else             { recognition.start(); }
    });

    document.getElementById('sw-clear-btn').addEventListener('click', () => {
      const msgs = document.getElementById('sw-messages');
      // Remove all rows except welcome
      msgs.querySelectorAll('.sw-msg-row:not(#sw-welcome-row)').forEach(r => r.remove());
      msgHistory = [];
    });

    // Role bar (landing page only)
    document.querySelectorAll('.sw-role-btn').forEach(btn => {
      btn.addEventListener('click', () => _setRole(btn.dataset.role));
    });

    // Show badge after 3s on first load (subtle attention)
    setTimeout(() => {
      if (!isOpen) {
        unreadCount = 1;
        const badge = document.getElementById('sw-notif-badge');
        badge.textContent = '1';
        badge.classList.add('show');
      }
    }, 3000);
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
