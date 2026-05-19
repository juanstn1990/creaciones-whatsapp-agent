#!/usr/bin/env python3
"""
Prueba el agente en la terminal antes de conectarlo a WhatsApp.
Uso: python3 test_chat.py
"""
import os
from pathlib import Path
from openai import OpenAI

PROMPT_FILE = Path(__file__).parent / "system_prompt.txt"

def load_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8").strip()

def main():
    api_key = os.environ.get("MOONSHOT_API_KEY")
    base_url = os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
    model = os.environ.get("MOONSHOT_MODEL", "moonshot-v1-8k")

    if not api_key:
        print("ERROR: falta MOONSHOT_API_KEY en el entorno.")
        print("  export MOONSHOT_API_KEY=sk-...")
        return

    client = OpenAI(api_key=api_key, base_url=base_url)
    system_prompt = load_prompt()
    history = []

    print(f"\n{'='*50}")
    print("  PRUEBA DE AGENTE — Creaciones")
    print(f"  Modelo: {model}")
    print(f"  System prompt: {len(system_prompt)} chars")
    print("  Escribe como si fueras el cliente de WhatsApp.")
    print("  Comandos: 'salir' para terminar, 'limpiar' para nueva conversación")
    print(f"{'='*50}\n")

    while True:
        try:
            user_input = input("CLIENTE: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo...")
            break

        if not user_input:
            continue
        if user_input.lower() == "salir":
            break
        if user_input.lower() == "limpiar":
            history.clear()
            print("\n--- nueva conversación ---\n")
            continue

        history.append({"role": "user", "content": user_input})

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}] + history,
            temperature=0.7,
            max_tokens=512,
        )

        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        print(f"\nAGENTE: {reply}\n")

if __name__ == "__main__":
    main()
