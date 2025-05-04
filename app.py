import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import os
import time
import uuid
import random
import string
from datetime import datetime
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.secret_key = '912882uuoopa1993o094ok42;24981io3o9'
socketio = SocketIO(app)

RESELLERS_FILE = 'resellers.json'
KEYS_FILE = 'keys.json'

def load_json(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

@app.template_filter('datetimeformat')
def datetimeformat(value):
    if isinstance(value, str) and value == "pending":
        return "Pendente"
    try:
        return datetime.fromtimestamp(int(value)).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(value)

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        resellers = load_json(RESELLERS_FILE)
        if username in resellers and resellers[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Credenciais inválidas.')
    return render_template('login.html')

@app.context_processor
def inject_reseller_name():
    name = None
    greeting = "Olá"
    profile = None

    if 'username' in session:
        resellers = load_json(RESELLERS_FILE)
        username = session['username']
        reseller = resellers.get(username, {})

        name = reseller.get('name', username)
        profile = reseller.get('profile', 'default.png')  # caminho da imagem padrão

        hour = datetime.now().hour
        if 5 <= hour < 12:
            greeting = "Bom dia"
        elif 12 <= hour < 18:
            greeting = "Boa tarde"
        else:
            greeting = "Boa noite"

    return dict(reseller_name=name, greeting=greeting, reseller_profile=profile)

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    resellers = load_json(RESELLERS_FILE)
    keys = load_json(KEYS_FILE)
    username = session['username']
    name = resellers[username].get('name', username)

    # Saudação com base no horário
    hour = datetime.now().hour
    if hour < 12:
        greeting = "Bom dia"
    elif hour < 18:
        greeting = "Boa tarde"
    else:
        greeting = "Boa noite"

    now = time.time()
    user_keys = [v for v in keys.values() if v.get("generated_by") == username]

    total_keys = len(user_keys)
    android_total = sum(1 for k in user_keys if k.get('device') == 'android')
    iphone_total = sum(1 for k in user_keys if k.get('device') == 'iphone')

    # Separar keys pendentes
    pending_keys = [k for k in user_keys if k.get('expires_at') == 'pending']
    pending_android = sum(1 for k in pending_keys if k.get('device') == 'android')
    pending_iphone = sum(1 for k in pending_keys if k.get('device') == 'iphone')

    # Considerar apenas as que não são pendentes
    non_pending_keys = [k for k in user_keys if k.get('expires_at') != 'pending']

    active_keys = [k for k in non_pending_keys if k.get('expires_at') > now]
    expired_keys = [k for k in non_pending_keys if k.get('expires_at') <= now]

    active_total = len(active_keys)
    expired_total = len(expired_keys)

    active_android = sum(1 for k in active_keys if k.get('device') == 'android')
    expired_android = sum(1 for k in expired_keys if k.get('device') == 'android')

    active_iphone = sum(1 for k in active_keys if k.get('device') == 'iphone')
    expired_iphone = sum(1 for k in expired_keys if k.get('device') == 'iphone')

    return render_template(
        'dashboard.html',
        reseller_name=name,
        greeting=greeting,
        total_keys=total_keys,
        android_total=android_total,
        iphone_total=iphone_total,
        keys_active=active_total,
        active_android=active_android,
        active_iphone=active_iphone,
        keys_expired=expired_total,
        expired_android=expired_android,
        expired_iphone=expired_iphone,
        keys_pending=len(pending_keys),
        pending_android=pending_android,
        pending_iphone=pending_iphone
    )

@app.route('/generate_key', methods=['GET', 'POST'])
def generate_key():
    if 'username' not in session:
        return redirect(url_for('login'))

    games_data = load_json("games.json")
    game_names = list(games_data.keys())

    if request.method == 'POST':
        duration = request.form.get('duration')
        game_name = request.form.get('game')
        device = request.form.get('device')
        amount = int(request.form.get("amount", 1))

        valid_durations = {
            '1h': 3600,
            '1d': 86400,
            '7d': 604800,
            '15d': 1296000,
            '30d': 2592000
        }

        if duration not in valid_durations or not game_name or not device or amount not in [1, 5, 10]:
            return render_template('generate_key.html', error='Preencha todos os campos corretamente.', games=game_names, games_data=games_data)

        resellers = load_json(RESELLERS_FILE)
        keys = load_json(KEYS_FILE)
        username = session['username']
        reseller = resellers[username]

        if reseller['credits'] < amount:
            return render_template('generate_key.html', error='Créditos insuficientes.', games=game_names, games_data=games_data)

        now = int(time.time())
        uid = games_data[game_name]['uid']
        reseller_name_lower = reseller.get("name", username).replace(" ", "").lower()

        generated_keys = []

        for _ in range(amount):
            random_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            new_key = f"{reseller_name_lower}-{duration}-{random_part}"

            key_info = {
                'android_id': None,
                'iphone_id': None,
                'device': device,
                'expires_at': "pending",  # << Aqui está a mudança
                'duration': duration,     # << Novo campo
                'created_at': now,
                'generated_by': username,
                'game': game_name,
                'game_uid': uid,
                'disabled': False
            }

            keys[new_key] = key_info
            generated_keys.append(new_key)

        reseller['credits'] -= amount
        save_json(KEYS_FILE, keys)
        save_json(RESELLERS_FILE, resellers)

        formatted = "<br>".join(generated_keys)
        return render_template('generate_key.html', success=f"Chaves geradas:<br>{formatted}", games=game_names, games_data=games_data)

    return render_template('generate_key.html', games=game_names, games_data=games_data)

@app.route('/renew_key', methods=['POST'])
def renew_key():
    if 'username' not in session:
        return redirect(url_for('login'))

    key_to_renew = request.form.get("key")
    duration = request.form.get("duration")
    durations = {
        '1h': 3600,
        '1d': 86400,
        '7d': 604800,
        '15d': 1296000,
        '30d': 2592000
    }

    if duration not in durations:
        return "Duração inválida.", 400

    keys = load_json(KEYS_FILE)
    resellers = load_json(RESELLERS_FILE)
    username = session['username']
    reseller = resellers.get(username)

    if key_to_renew not in keys:
        return "Chave não encontrada.", 404

    if reseller['credits'] < 1:
        return "Créditos insuficientes.", 403

    # Atualiza o tempo de expiração
    now = int(time.time())
    current_expiry = keys[key_to_renew].get('expires_at', now)
    keys[key_to_renew]['expires_at'] = current_expiry + durations[duration]

    # Consome crédito
    reseller['credits'] -= 1

    save_json(KEYS_FILE, keys)
    save_json(RESELLERS_FILE, resellers)

    return redirect(url_for('view_keys'))

@app.route('/view_keys')
def view_keys():
    if 'username' not in session:
        return redirect(url_for('login'))

    # 1) se faltar sort, reenvia todos os args + sort=recent
    if 'sort' not in request.args:
        args = request.args.to_dict()
        args['sort'] = 'recent'
        return redirect(url_for('view_keys', **args))

    # 2) captura parâmetros
    sort_order   = request.args.get('sort', 'recent')
    search_term  = (request.args.get('search') or '').strip().lower()

    # 3) carrega e filtra só as chaves do usuário
    all_keys = load_json(KEYS_FILE)
    user_keys = {
        k: v for k, v in all_keys.items()
        if v.get('generated_by') == session['username']
    }

    # 4) aplica filtro de busca, se houver termo
    if search_term:
        def matches(k, info):
            return (
                search_term in k.lower()
                or search_term in info.get('game','').lower()
                or search_term in info.get('device','').lower()
            )
        user_keys = {k: v for k, v in user_keys.items() if matches(k, v)}

    # 5) ordena pelo created_at
    #    (se for string ISO, nosso filter já converte)
    sorted_items = sorted(
        user_keys.items(),
        key=lambda item: (
            datetime.fromisoformat(item[1]['created_at'])
            if isinstance(item[1]['created_at'], str)
            else item[1]['created_at']
        ),
        reverse=(sort_order == 'recent')
    )
    sorted_keys = dict(sorted_items)

    # 6) renderiza, enviando também current_search
    return render_template(
        'keys.html',
        keys=sorted_keys,
        current_sort=sort_order,
        current_search=search_term
    )

@app.route("/delete_keys", methods=["POST"])
def delete_keys():
    selected_keys = request.form.getlist("selected_keys")
    if not selected_keys:
        return redirect("/view_keys")  # ou url_for se tiver a função definida

    keys = load_json(KEYS_FILE)
    for key in selected_keys:
        if key in keys:
            del keys[key]

    save_json(KEYS_FILE, keys)
    return redirect("/view_keys")

@app.route('/update_profile_picture', methods=['POST'])
def update_profile_picture():
    if 'username' not in session:
        return redirect(url_for('login'))

    file = request.files.get('profile_picture')
    if file and file.filename.endswith(('.png', '.jpg', '.jpeg', '.gif')):
        filename = f"{session['username']}_{uuid.uuid4().hex[:8]}.png"
        save_path = os.path.join('static', 'avatars', filename)
        file.save(save_path)

        resellers = load_json(RESELLERS_FILE)
        resellers[session['username']]['profile'] = f"avatars/{filename}"
        save_json(RESELLERS_FILE, resellers)

    return redirect(url_for('dashboard'))

@app.route('/messages')
def messages():
    if 'username' not in session:
        return redirect(url_for('login'))

    usuario_logado = session['username']

    with open('messages.json', 'r', encoding='utf-8') as f:
        todas = json.load(f)

    conversas = []
    arquivadas = []
    resellers = load_json(RESELLERS_FILE)

    for c in todas:
        if usuario_logado in c.get('participants', []):
            outro = [p for p in c['participants'] if p != usuario_logado][0]
            ultima_msg = c['messages'][-1] if c['messages'] else None

            if usuario_logado in c.get('ocultos', []):
                continue  # oculto, não mostra

            # ✅ Aqui é o lugar certo para pegar o profile
            profile = resellers.get(outro, {}).get('profile', 'default.png')

            data = {
                "com": outro,
                "profile": url_for('static', filename=profile),
                "ultima_msg": ultima_msg['text'] if ultima_msg else '',
                "quando": ultima_msg['timestamp'] if ultima_msg else '',
                "nao_lidas": len([
                    m for m in c['messages']
                    if m['sender'] != usuario_logado and not m.get('read', False)
                ])
            }

            if usuario_logado in c.get('arquivados', []):
                arquivadas.append(data)
            else:
                conversas.append(data)

    conversas = sorted(conversas, key=lambda x: x['quando'], reverse=True)
    arquivadas = sorted(arquivadas, key=lambda x: x['quando'], reverse=True)

    return render_template("messages.html", conversas=conversas, arquivadas=arquivadas)

@app.route('/buscar_usuarios')
def buscar_usuarios():
    termo = request.args.get('q', '').lower()
    resellers = load_json(RESELLERS_FILE)

    resultados = []
    for username, dados in resellers.items():
        name = dados.get('name', '')
        profile = dados.get('profile', 'default.png')
        if termo in name.lower():
            resultados.append({
                'name': name,
                'username': username,
                'profile': url_for('static', filename=profile)
            })

    return jsonify(resultados)


@app.route('/enviar_mensagem', methods=['POST'])
def enviar_mensagem():
    sender = session.get('username')
    receiver_name = request.form.get('usuario')
    mensagem = request.form.get('mensagem')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not sender or not receiver_name or not mensagem:
        return redirect(url_for('messages'))

    resellers = load_json(RESELLERS_FILE)
    receiver = None
    for username, dados in resellers.items():
        if dados.get('name') == receiver_name:
            receiver = username
            break

    if not receiver:
        return "Destinatário não encontrado", 400

    nova_msg = {
        "sender": sender,
        "text": mensagem,
        "timestamp": timestamp
    }

    caminho = "messages.json"
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            mensagens = json.load(f)
    else:
        mensagens = []

    for conversa in mensagens:
        if sorted([sender, receiver]) == sorted(conversa["participants"]):
            conversa["messages"].append(nova_msg)
            break
    else:
        mensagens.append({
            "participants": [sender, receiver],
            "messages": [nova_msg],
            "ocultos": [],
            "arquivados": []
        })

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(mensagens, f, ensure_ascii=False, indent=4)

    return redirect(url_for('messages'))


@app.route('/chat/<username>', methods=['GET', 'POST'])
def chat(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    usuario_logado = session['username']
    mensagens = []
    room = ''.join(sorted([usuario_logado, username]))

    caminho = 'messages.json'
    if os.path.exists(caminho):
        with open(caminho, 'r', encoding='utf-8') as f:
            todas = json.load(f)
    else:
        todas = []

    atualizou_leitura = False  # <- para saber se precisa salvar depois

    for conversa in todas:
        participantes = conversa.get('participants', [])
        if sorted(participantes) == sorted([usuario_logado, username]):
            if usuario_logado in conversa.get('ocultos', []):
                conversa['ocultos'].remove(usuario_logado)
            if usuario_logado in conversa.get('arquivados', []):
                conversa['arquivados'].remove(usuario_logado)

            mensagens = conversa['messages']
            for m in mensagens:
                if m['sender'] != usuario_logado and not m.get('read', False):
                    m['read'] = True
                    atualizou_leitura = True
            break

    # Envio de nova mensagem
    if request.method == 'POST':
        texto = request.form.get('mensagem')
        if texto:
            nova = {
                "sender": usuario_logado,
                "text": texto,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "read": False
            }

            for conversa in todas:
                if sorted(conversa['participants']) == sorted([usuario_logado, username]):
                    conversa['messages'].append(nova)
                    break
            else:
                todas.append({
                    "participants": [usuario_logado, username],
                    "messages": [nova],
                    "ocultos": [],
                    "arquivados": []
                })

            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(todas, f, ensure_ascii=False, indent=4)

            return redirect(url_for('chat', username=username))

    # Salva alterações se teve leitura marcada
    if atualizou_leitura:
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(todas, f, ensure_ascii=False, indent=4)

    resellers = load_json(RESELLERS_FILE)
    outro_nome = resellers.get(username, {}).get('name', username)
    outro_profile = url_for('static', filename=resellers.get(username, {}).get('profile', 'default.png'))

    return render_template(
        'chat.html',
        mensagens=mensagens,
        outro_usuario=username,
        outro_nome=outro_nome,
        outro_profile=outro_profile,
        room=room  # 🔥 importante para o JS funcionar
    )

@app.route('/acoes_chat', methods=['POST'])
def acoes_chat():
    if 'username' not in session:
        return redirect(url_for('login'))

    usuario = session['username']
    selecionados = request.form.getlist('selecionados')
    acao = request.form.get('acao')

    if not selecionados or not acao:
        return redirect(url_for('messages'))

    with open('messages.json', 'r', encoding='utf-8') as f:
        conversas = json.load(f)

    for conversa in conversas:
        participantes = conversa.get('participants', [])
        outro = [p for p in participantes if p != usuario][0]

        if outro in selecionados:
            if acao == 'ocultar':
                conversa.setdefault('ocultos', []).append(usuario)
                conversa['ocultos'] = list(set(conversa['ocultos']))
            elif acao == 'arquivar':
                conversa.setdefault('arquivados', []).append(usuario)
                conversa['arquivados'] = list(set(conversa['arquivados']))
            elif acao == 'desarquivar':
                if usuario in conversa.get('arquivados', []):
                    conversa['arquivados'].remove(usuario)

    with open('messages.json', 'w', encoding='utf-8') as f:
        json.dump(conversas, f, ensure_ascii=False, indent=4)

    return redirect(url_for('messages'))


@app.route('/arquivadas')
def arquivadas():
    if 'username' not in session:
        return redirect(url_for('login'))

    usuario_logado = session['username']

    with open('messages.json', 'r', encoding='utf-8') as f:
        todas = json.load(f)

    arquivadas = []

    for c in todas:
        if usuario_logado in c.get('participants', []) and usuario_logado in c.get('arquivados', []):
            outro = [p for p in c['participants'] if p != usuario_logado][0]
            ultima_msg = c['messages'][-1] if c['messages'] else None

            nao_lidas = len([
                m for m in c['messages']
                if m['sender'] != usuario_logado and not m.get('read', False)
            ])

            arquivadas.append({
                "com": outro,
                "ultima_msg": ultima_msg['text'] if ultima_msg else '',
                "quando": ultima_msg['timestamp'] if ultima_msg else '',
                "nao_lidas": nao_lidas
            })

    arquivadas = sorted(arquivadas, key=lambda x: x['quando'], reverse=True)
    return render_template("arquivadas.html", arquivadas=arquivadas)

socketio = SocketIO(app, cors_allowed_origins="*")

online_users = {}  # dict: {username: room}

@socketio.on('join')
def handle_join(data):
    room = data['room']
    username = data.get('username')
    if username:
        online_users[username] = room
    join_room(room)
    emit('typing', {'room': room, 'sender': None}, room=room)

@socketio.on('typing')
def handle_typing(data):
    emit('typing', data, room=data['room'], include_self=False)

@socketio.on('send_message')
def handle_send_message(data):
    sender = data['sender']
    receiver = data['receiver']
    text = data['text']
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    room = ''.join(sorted([sender, receiver]))

    caminho = 'messages.json'
    if os.path.exists(caminho):
        with open(caminho, 'r', encoding='utf-8') as f:
            mensagens = json.load(f)
    else:
        mensagens = []

    updated = False
    nova = {
        "sender": sender,
        "text": text,
        "timestamp": timestamp,
        "read": False
    }

    for conversa in mensagens:
        if sorted(conversa['participants']) == sorted([sender, receiver]):
            conversa['messages'].append(nova)
            # ✅ MARCAR como lidas as do outro lado (caso esteja vendo)
            for m in conversa['messages']:
                if m['sender'] == receiver and not m.get('read', False):
                    m['read'] = True
                    updated = True
            break
    else:
        mensagens.append({
            "participants": [sender, receiver],
            "messages": [nova],
            "ocultos": [],
            "arquivados": []
        })

    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(mensagens, f, ensure_ascii=False, indent=4)

    # Enviar mensagem para sala
    emit('new_message', nova, room=room, include_self=False)

    # ✅ Se marcou como lido, informe remetente original
    if updated:
        emit('read_receipt', { 'reader': sender, 'for': receiver }, room=room, include_self=False)


@socketio.on('mark_read')
def handle_mark_read(data):
    user = data['user']
    other = data['other']
    room = ''.join(sorted([user, other]))

    caminho = 'messages.json'
    if os.path.exists(caminho):
        with open(caminho, 'r', encoding='utf-8') as f:
            mensagens = json.load(f)
    else:
        return

    updated = False
    for conversa in mensagens:
        if sorted(conversa['participants']) == sorted([user, other]):
            for m in conversa['messages']:
                if m['sender'] == other and not m.get('read', False):
                    m['read'] = True
                    updated = True
            break

    if updated:
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(mensagens, f, ensure_ascii=False, indent=4)

        # Só emite se o remetente estiver online
        if other in online_users:
            emit('read_receipt', { 'reader': user, 'for': other }, room=online_users[other])

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=7700, debug=True)

