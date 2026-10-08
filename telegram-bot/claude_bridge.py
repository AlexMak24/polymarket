#!/usr/bin/env python3
"""Claude TG бот через Prismatic API."""

import httpx, os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN = "8971389528:AAFCbvrEpdl0xnb8LWWt6x4Clah0QXgGmSE"
API_KEY = "pa_If3vuVQuN0-E0gogqJWewI8ChI22VoZLJKQEu-huz2k"
API_URL = "https://api.prismaticapi.com/v1/chat/completions"

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != 793784229: return
    text = update.message.text
    msg = await update.message.reply_text("...")
    
    try:
        r = httpx.post(API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": "claude-sonnet-4.6", "max_tokens": 4000,
                  "messages": [{"role": "user", "content": f"Ответь на русском. {text}"}]},
            timeout=120)
        data = r.json()
        reply = data["choices"][0]["message"]["content"]
        for chunk in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
            if chunk == reply[:4000]: await msg.edit_text(chunk)
            else: await update.message.reply_text(chunk)
    except Exception as e:
        await msg.edit_text(f"ERR: {e}")

app = Application.builder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
print("Claude TG бот → Prismatic API (8 моделей)")
app.run_polling(drop_pending_updates=True)
