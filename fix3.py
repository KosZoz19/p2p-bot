with open('bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# For videos
old_video = '''                if i in COURSE_POST_VIDEOS:
                    video_path = COURSE_POST_VIDEOS[i]
                    await _send_file_with_fallback(chat_id, video_path, None, reply_markup=None)
                    await bot.send_message(chat_id, text, reply_markup=kb_course())'''

new_video = '''                if i in COURSE_POST_VIDEOS:
                    video_path = COURSE_POST_VIDEOS[i]
                    await _send_file_with_fallback(chat_id, video_path, text[:1024], reply_markup=kb_course())'''

content = content.replace(old_video, new_video)

# For banner
old_banner = '''                    if isinstance(media, str):  # banner
                        await bot.send_photo(chat_id, media, caption=None, reply_markup=None)
                        await bot.send_message(chat_id, text, reply_markup=kb_course())'''

new_banner = '''                    if isinstance(media, str):  # banner
                        await bot.send_photo(chat_id, media, caption=text[:1024], reply_markup=kb_course())'''

content = content.replace(old_banner, new_banner)

# For single photo
old_single = '''                        if len(media) == 1:
                            photo = COURSE_POST_PHOTOS[media[0]]
                            await bot.send_photo(chat_id, photo, caption=None, reply_markup=None)
                            await bot.send_message(chat_id, text, reply_markup=kb_course())'''

new_single = '''                        if len(media) == 1:
                            photo = COURSE_POST_PHOTOS[media[0]]
                            await bot.send_photo(chat_id, photo, caption=text[:1024], reply_markup=kb_course())'''

content = content.replace(old_single, new_single)

# For media group
old_group = '''                        elif len(media) > 1:
                            # send media group as gallery
                            media_group = [InputMediaPhoto(media=COURSE_POST_PHOTOS[idx]) for idx in media]
                            media_group[0].caption = None
                            await bot.send_media_group(chat_id, media_group)
                            await bot.send_message(chat_id, text, reply_markup=kb_course())'''

new_group = '''                        elif len(media) > 1:
                            # send media group as gallery
                            media_group = [InputMediaPhoto(media=COURSE_POST_PHOTOS[idx]) for idx in media]
                            media_group[0].caption = text[:1024]
                            await bot.send_media_group(chat_id, media_group)'''

content = content.replace(old_group, new_group)

with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(content)
