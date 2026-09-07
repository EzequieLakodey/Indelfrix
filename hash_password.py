#!/usr/bin/env python3
"""Genera un hash seguro para la contraseña de administrador.

Uso:
    python hash_password.py "mi_contraseña"

Copiar la salida y pegarla como valor de ADMIN_PASS en .env.
"""
import sys
from werkzeug.security import generate_password_hash


def main():
    if len(sys.argv) < 2:
        print('Uso: python hash_password.py "mi_contraseña"')
        sys.exit(1)
    password = sys.argv[1]
    print(generate_password_hash(password))


if __name__ == '__main__':
    main()
