import base64

def encrypt_text(plain_text, secret_key):
    """Cifra un texto plano usando una clave secreta para ocultar los metadatos en la nube"""
    if not secret_key:
        return plain_text
    key_bytes = secret_key.encode('utf-8')
    text_bytes = plain_text.encode('utf-8')
    
    encrypted_bytes = bytearray(
        b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(text_bytes)
    )
    return base64.b64encode(encrypted_bytes).decode('utf-8')

def decrypt_text(encrypted_text, secret_key):
    """Descifra el texto recuperado de la nube usando la misma clave secreta"""
    if not secret_key:
        return encrypted_text
    try:
        key_bytes = secret_key.encode('utf-8')
        decoded_bytes = base64.b64decode(encrypted_text.encode('utf-8'))
        
        decrypted_bytes = bytearray(
            b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(decoded_bytes)
        )
        return decrypted_bytes.decode('utf-8')
    except Exception:
        return None