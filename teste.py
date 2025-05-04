import asyncio
import json
import time
import os
import base64
import traceback
from aiohttp import web, WSMsgType
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256

# --- Chaves ofuscadas ---
OBFUSCATED_AES_KEY = bytes([0x61, 0x46, 0x63, 0x11, 0x18, 0x12, 0x50, 0x6C,
    0x74, 0x78, 0x52, 0x7A, 0x19, 0x65, 0x42, 0x4D])
AES_KEY_PATTERN = [3, 7, 13, 0, 9, 10, 11, 2, 14, 6, 12, 8, 15, 5, 4, 1]
AES_KEY_XOR = 32

OBFUSCATED_AES_IV = bytes([0xEF, 0x8A, 0xF2, 0x8B, 0xDE, 0xFB, 0xFC, 0xC2,
    0x8D, 0xCB, 0xF0, 0x83, 0xF8, 0xCC, 0x8E, 0xF9])
AES_IV_PATTERN = [6, 4, 12, 10, 13, 14, 5, 11, 2, 7, 3, 9, 1, 8, 15, 0]
AES_IV_XOR = 186

def restore_obfuscated_key(obf, pattern, xor_val):
    return bytes([obf[pattern[i]] ^ xor_val for i in range(16)])

AES_KEY = restore_obfuscated_key(OBFUSCATED_AES_KEY, AES_KEY_PATTERN, AES_KEY_XOR)
AES_IV  = restore_obfuscated_key(OBFUSCATED_AES_IV, AES_IV_PATTERN, AES_IV_XOR)

def zero_unpad(data: bytes) -> bytes:
    return data.rstrip(b'\x00')

def decrypt_and_verify(data_b64: str) -> dict:
    raw = base64.b64decode(data_b64)
    if len(raw) < 32:
        raise Exception("Dados insuficientes")
    ciphertext = raw[:-32]
    mac = raw[-32:]
    h = HMAC.new(AES_KEY, digestmod=SHA256)
    h.update(ciphertext)
    h.verify(mac)
    decrypted = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).decrypt(ciphertext)
    return json.loads(zero_unpad(decrypted).decode('utf-8'))

def encrypt_and_sign(data: dict) -> str:
    raw = json.dumps(data, separators=(',', ':')).encode('utf-8')
    raw += b'\x00' * ((16 - len(raw) % 16) % 16)
    enc = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(raw)
    h = HMAC.new(AES_KEY, digestmod=SHA256)
    h.update(enc)
    mac = h.digest()
    return base64.b64encode(enc + mac).decode()

# --- Utilitários ---
KEYS_FILE = "keys.json"
def load_keys():
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, "r") as f: return json.load(f)
    return {}

def save_keys(data):
    with open(KEYS_FILE, "w") as f: json.dump(data, f, indent=4)


async def handle_auth(request):
    try:
        valid_durations = {
    '1h': 3600,
    '1d': 86400,
    '7d': 604800,
    '15d': 1296000,
    '30d': 2592000
}

        raw_b64 = await request.text()
        print(f"[AUTH] Base64 recebido (início): {raw_b64[:60]}...")

        data = decrypt_and_verify(raw_b64)
        print(f"[AUTH] Dados decifrados: {data}")

        android_id = data.get("id")
        key = str(data.get("key", "")).strip()
        timestamp = data.get("timestamp")
        current_update = data.get("current_update")
        game_uid_client = data.get("game_uid")

        if not all([android_id, key, timestamp, current_update, game_uid_client]):
            raise Exception("Campos obrigatórios ausentes")

        if current_update != "1.0.0":
            raise Exception("Nova atualização disponível")

        keys = load_keys()
        now = int(time.time())

        if key not in keys:
            raise Exception("Key não existe")

        info = keys[key]

        # 🔒 Verifica se a key está desativada manualmente
        if info.get("disabled") is True:
            raise Exception("Key desativada")

        # 🔒 Verifica se o UID da key bate com o do cliente
        game_uid_key = info.get("game_uid")
        if not game_uid_key or game_uid_key != game_uid_client:
            raise Exception("Essa key não pertence ao pacote atual")

        # 🔒 Verifica se já foi usada em outro dispositivo
        if info.get("android_id") is not None and info["android_id"] != android_id:
            raise Exception("Key usada em outro dispositivo")

        # ✅ Ativa a key se estiver pendente
        if info.get("expires_at") == "pending":
            duration_key = info.get("duration")
            duration_seconds = valid_durations.get(duration_key)

            if not duration_seconds:
                raise Exception("Duração inválida ou não definida na key")

            expires_at = now + duration_seconds
            info["expires_at"] = expires_at
            print(f"[AUTH] Ativando key '{key}' por {duration_key} (expira em {expires_at})")
            keys[key] = info
            save_keys(keys)
        else:
            if now > info["expires_at"]:
                raise Exception("Key expirada")

        if info.get("android_id") is None:
            print(f"[AUTH] Registrando novo Android ID para a key {key}")
            info["android_id"] = android_id
            keys[key] = info
            save_keys(keys)

        response = {
            "id": android_id,
            "key": key,
            "timestamp": now,
            "expires_at": info["expires_at"],
            "success": True,
            "version": current_update,
            "uid": game_uid_key
        }

        print(f"[AUTH] Sucesso: {response}")
        return web.Response(text=encrypt_and_sign(response))

    except Exception as e:
        print(f"[AUTH][ERRO] {str(e)}")
        traceback.print_exc()
        err = {
            "success": False,
            "title": "Erro",
            "message": str(e)
        }
        return web.Response(text=encrypt_and_sign(err), status=400)

async def handle_key_info(request):
    try:
        data = await request.json()
        key = data.get("key", "")
        print(f"[INFO] Consulta de expiração para key: {key}")
        keys = load_keys()
        if key not in keys:
            return web.json_response({"success": False, "message": "Key não encontrada"}, status=404)
        ts = keys[key].get("expires_at", 0)
        date = time.strftime("%d-%m-%Y %H:%M:%S", time.localtime(ts))
        return web.json_response({"success": True, "expires_at": date})
    except Exception as e:
        print(f"[INFO][ERRO] {str(e)}")
        traceback.print_exc()
        return web.json_response({"success": False, "message": f"Erro interno: {str(e)}"}, status=500)

async def handle_key_status(request):
    print("[STATUS] Requisição de status recebida")
    try:
        data = await request.json()
        key = data.get("key", "").strip()
        print(f"[STATUS] Key recebida: {key}")

        keys = load_keys()
        now = int(time.time())

        if key not in keys:
            print("[STATUS] Resultado: disabled (key não encontrada)")
            return web.json_response({"status": "disabled"})

        info = keys[key]
        expires_at = info.get("expires_at", 0)
        print(f"[STATUS] Expiração registrada: {expires_at} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))})")
        print(f"[STATUS] Timestamp atual: {now} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))})")

        if now > expires_at:
            print("[STATUS] Resultado: expired")
            return web.json_response({"status": "expired"})

        print("[STATUS] Resultado: active")
        return web.json_response({"status": "active"})

    except Exception as e:
        print(f"[STATUS][ERRO] {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# --- Inicialização ---
app = web.Application()
app.router.add_post("/auth", handle_auth)
app.router.add_post("/key/info", handle_key_info)
app.router.add_post("/key/status", handle_key_status)

if __name__ == "__main__":
    print("[SERVER] Servidor iniciado em http://0.0.0.0:7713")
    web.run_app(app, host="0.0.0.0", port=7713)
