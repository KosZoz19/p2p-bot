with open('bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('            await asyncio.sleep(10)  # 5 часов между постами', '            await asyncio.sleep(18000)  # 5 часов между постами')

with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(content)
