from flask import Flask, request, jsonify
from flask_cors import CORS
import os, requests
from datetime import datetime

app  = Flask(__name__)
CORS(app)

# ── Env Vars (set these in Render dashboard) ──────────────────────────
SUPABASE_URL        = os.environ.get('SUPABASE_URL',        '')
SUPABASE_KEY        = os.environ.get('SUPABASE_KEY',        '')
TELEGRAM_BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN',  '')
GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY',      '')
BOT_USERNAME        = os.environ.get('BOT_USERNAME',        'StudyVaultBot')
WEBAPP_URL          = os.environ.get('WEBAPP_URL',          '')

# ── Milestone table ───────────────────────────────────────────────────
MILESTONE_REWARDS = {
    1:2, 2:5, 3:10, 5:20, 10:45, 20:100, 50:300, 100:750
}
MILESTONES = sorted(MILESTONE_REWARDS.keys())

# ── Academic system prompt ────────────────────────────────────────────
SYSTEM_PROMPT = """You are StudyVault AI — a world-class academic assistant for students at ALL levels globally:
• Primary School
• Junior Secondary School (JSS 1–3)
• Senior Secondary School / WAEC / NECO (SSS 1–3)
• JAMB / UTME candidates
• University / Undergraduate
• Postgraduate

STRICT RESPONSE FORMAT:
1. Start with a clear heading that restates the topic
2. Use numbered steps for processes and equations
3. Use bullet points for lists and definitions
4. For MATHEMATICS — show every working step, state formula first
5. For SCIENCES — state laws/principles, give examples, explain diagrams in text
6. For JAMB — align with official JAMB syllabus; note common exam traps
7. For ESSAYS — provide introduction, 3+ body paragraphs, conclusion
8. For RESEARCH — organize into clear sections with key findings
9. Be accurate, thorough, and encouraging at all times
10. Always close with: 💡 Key Takeaway: [one clear summary sentence]"""

# ── Supabase REST helper ──────────────────────────────────────────────
def db(method, table, data=None, query=''):
    url  = f"{SUPABASE_URL}/rest/v1/{table}" + (f"?{query}" if query else '')
    hdrs = {
        'apikey':        SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type':  'application/json',
        'Prefer':        'return=representation'
    }
    try:
        fn = {'GET':requests.get,'POST':requests.post,'PATCH':requests.patch}[method]
        r  = fn(url, headers=hdrs, json=data, timeout=10)
        return r.json() if r.content else []
    except Exception as e:
        print(f"DB[{table}] {method} error: {e}")
        return []

# ── Telegram send helper ──────────────────────────────────────────────
def tg_send(chat_id, text, markup=None):
    payload = {'chat_id':chat_id, 'text':text, 'parse_mode':'HTML'}
    if markup:
        payload['reply_markup'] = markup
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=10
        )
    except Exception as e:
        print(f"TG send error: {e}")

# ── Referral processor ────────────────────────────────────────────────
def process_referral(referrer_id, new_user_id):
    if str(referrer_id) == str(new_user_id):
        return
    ref = db('GET', 'users', query=f'id=eq.{referrer_id}')
    if not ref:
        return
    ref         = ref[0]
    new_total   = ref['total_referred'] + 1
    new_tokens  = ref['tokens'] + 1        # +1 credit per referral
    db('PATCH', 'users',
       data={'total_referred': new_total, 'tokens': new_tokens},
       query=f'id=eq.{referrer_id}')
    # unlock milestone records
    for m in MILESTONES:
        if new_total >= m:
            if not db('GET', 'milestones',
                      query=f'user_id=eq.{referrer_id}&milestone=eq.{m}'):
                db('POST', 'milestones', data={
                    'user_id':    referrer_id,
                    'milestone':  m,
                    'reward':     MILESTONE_REWARDS[m],
                    'claimed':    False,
                    'created_at': datetime.utcnow().isoformat()
                })

# ══════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.route('/health')
def health():
    return jsonify({'status':'alive','service':'StudyVault'}), 200

# ── Telegram Webhook ──────────────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    upd = request.json
    if 'message' not in upd:
        return jsonify({'ok':True})

    msg      = upd['message']
    chat_id  = msg['chat']['id']
    user_id  = str(msg['from']['id'])
    username = msg['from'].get('first_name', 'Student')
    text     = msg.get('text', '')

    if text.startswith('/start'):
        referred_by = None
        parts = text.split()
        if len(parts) > 1 and parts[1].startswith('ref_'):
            referred_by = parts[1][4:]

        existing = db('GET', 'users', query=f'id=eq.{user_id}')

        if not existing:
            db('POST', 'users', data={
                'id': user_id, 'username': username,
                'tokens': 5, 'total_referred': 0,
                'referred_by': referred_by,
                'is_premium': False, 'premium_plan': None,
                'ads_in_session': 0,
                'created_at': datetime.utcnow().isoformat()
            })
            if referred_by:
                process_referral(referred_by, user_id)
            body = (
                f"🎓 <b>Welcome to StudyVault, {username}!</b>\n\n"
                f"Your AI-powered academic assistant is ready.\n\n"
                f"✅ <b>5 FREE credits</b> added!\n\n"
                f"I help with:\n"
                f"📚 Assignments &amp; Projects\n"
                f"🎯 JAMB / WAEC / NECO Prep\n"
                f"🔬 Research &amp; Essays\n"
                f"📝 Tests &amp; Exams\n"
                f"🏫 All Subjects · All Levels · All Countries\n\n"
                f"Tap below to open your dashboard 👇"
            )
        else:
            body = f"👋 <b>Welcome back, {username}!</b>\n\nYour dashboard is ready 👇"

        tg_send(chat_id, body, markup={
            'inline_keyboard':[[{
                'text':    '🎓 Open StudyVault Dashboard',
                'web_app': {'url': WEBAPP_URL}
            }]]
        })
    return jsonify({'ok':True})

# ── API: Register user ────────────────────────────────────────────────
@app.route('/api/start', methods=['POST'])
def api_start():
    d           = request.json
    user_id     = str(d['user_id'])
    username    = d.get('username', 'Student')
    referred_by = d.get('referred_by')

    existing = db('GET', 'users', query=f'id=eq.{user_id}')
    milestones = db('GET', 'milestones',
                    query=f'user_id=eq.{user_id}&claimed=eq.false&order=milestone.asc')
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

    if existing:
        return jsonify({'user':existing[0],'new':False,
                        'unclaimed_milestones':milestones,'referral_link':ref_link})

    new_user = {
        'id':user_id,'username':username,'tokens':5,
        'total_referred':0,'referred_by':referred_by,
        'is_premium':False,'premium_plan':None,
        'ads_in_session':0,
        'created_at':datetime.utcnow().isoformat()
    }
    result = db('POST', 'users', data=new_user)
    if referred_by:
        process_referral(referred_by, user_id)

    return jsonify({'user':result[0] if result else new_user,'new':True,
                    'unclaimed_milestones':[],'referral_link':ref_link})

# ── API: Get user ─────────────────────────────────────────────────────
@app.route('/api/user/<uid>')
def get_user(uid):
    u = db('GET','users',query=f'id=eq.{uid}')
    if not u: return jsonify({'error':'Not found'}),404
    ms = db('GET','milestones',
            query=f'user_id=eq.{uid}&claimed=eq.false&order=milestone.asc')
    return jsonify({'user':u[0],'unclaimed_milestones':ms,
                    'referral_link':f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"})

# ── API: Record ad watch (ad_number = 1,2,3) ─────────────────────────
@app.route('/api/watch-ad', methods=['POST'])
def watch_ad():
    d         = request.json
    user_id   = str(d['user_id'])
    ad_number = int(d.get('ad_number', 1))

    u = db('GET','users',query=f'id=eq.{user_id}')
    if not u: return jsonify({'error':'Not found'}),404
    u = u[0]

    if ad_number >= 3:
        new_tokens = u['tokens'] + 1
        db('PATCH','users',
           data={'tokens':new_tokens,'ads_in_session':0},
           query=f'id=eq.{user_id}')
        return jsonify({'session_complete':True,'tokens':new_tokens,'ads_watched':3})
    else:
        db('PATCH','users',data={'ads_in_session':ad_number},query=f'id=eq.{user_id}')
        return jsonify({'session_complete':False,'ads_watched':ad_number,
                        'ads_remaining':3-ad_number})

# ── API: Ask AI ───────────────────────────────────────────────────────
@app.route('/api/ask-ai', methods=['POST'])
def ask_ai():
    d        = request.json
    user_id  = str(d['user_id'])
    question = d.get('question','').strip()
    subject  = d.get('subject','General')
    level    = d.get('level','General')

    if not question:
        return jsonify({'error':'No question provided'}),400

    u = db('GET','users',query=f'id=eq.{user_id}')
    if not u: return jsonify({'error':'Not found'}),404
    u = u[0]

    if not u['is_premium'] and u['tokens'] < 1:
        return jsonify({'error':'insufficient_tokens','tokens':0}),402

    answer = call_gemini(question, subject, level)
    if not answer:
        return jsonify({'error':'AI temporarily unavailable. Please try again.'}),500

    new_tokens = u['tokens']
    if not u['is_premium']:
        new_tokens = u['tokens'] - 1
        db('PATCH','users',data={'tokens':new_tokens},query=f'id=eq.{user_id}')

    db('POST','history',data={
        'user_id':user_id,'question':question,
        'answer':answer,'subject':subject,'level':level,
        'created_at':datetime.utcnow().isoformat()
    })

    return jsonify({
        'answer':  answer,
        'tokens':  new_tokens if not u['is_premium'] else 'unlimited'
    })

# ── Gemini Flash ──────────────────────────────────────────────────────
def call_gemini(question, subject, level):
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}")
        prompt = f"{SYSTEM_PROMPT}\n\nStudent Level: {level}\nSubject: {subject}\n\nQuestion:\n{question}"
        payload = {
            "contents":[{"parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":0.7,"maxOutputTokens":1500}
        }
        r = requests.post(url, json=payload, timeout=30)
        return r.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"Gemini error: {e}")
        return None

# ── API: Answer history ───────────────────────────────────────────────
@app.route('/api/history/<uid>')
def get_history(uid):
    h = db('GET','history',
           query=f'user_id=eq.{uid}&order=created_at.desc&limit=50')
    return jsonify({'history':h})

# ── API: Claim milestone ──────────────────────────────────────────────
@app.route('/api/claim-milestone', methods=['POST'])
def claim_milestone():
    d         = request.json
    user_id   = str(d['user_id'])
    milestone = int(d['milestone'])

    rec = db('GET','milestones',
             query=f'user_id=eq.{user_id}&milestone=eq.{milestone}&claimed=eq.false')
    if not rec:
        return jsonify({'error':'Already claimed or not unlocked'}),404

    reward = rec[0]['reward']
    u      = db('GET','users',query=f'id=eq.{user_id}')
    if not u: return jsonify({'error':'Not found'}),404

    new_tokens = u[0]['tokens'] + reward
    db('PATCH','users',data={'tokens':new_tokens},query=f'id=eq.{user_id}')
    db('PATCH','milestones',
       data={'claimed':True,'claimed_at':datetime.utcnow().isoformat()},
       query=f'user_id=eq.{user_id}&milestone=eq.{milestone}')

    return jsonify({'success':True,'reward':reward,'tokens':new_tokens})

# ── Run ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
