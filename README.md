# VideoGrab

Локальная программа для скачивания видео или звука по ссылке.

## Запуск на macOS

1. Откройте **Terminal**: нажмите `Cmd + Space`, введите `Terminal` и нажмите `Enter`.
2. В окне Terminal напечатайте `python3 ` — после команды обязательно оставьте пробел.
3. Перетащите файл `app.py` в окно Terminal. Его полный путь подставится сам.
4. Нажмите `Enter`.

Команда будет выглядеть примерно так:

```bash
python3 /Users/ваше-имя/Desktop/videograb/app.py
```

Вместо перетаскивания можно указать путь вручную:

```bash
cd /Users/ваше-имя/Desktop/videograb
python3 app.py
```

После запуска откройте в браузере [http://localhost:8742](http://localhost:8742), вставьте ссылку и выберите качество.

Для остановки программы вернитесь в Terminal и нажмите `Ctrl + C`.

## Требования

- Python 3
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- ffmpeg — нужен для склейки видео и звука в лучшем качестве, а также для конвертации в MP3

На macOS их можно установить через Homebrew:

```bash
brew install python yt-dlp ffmpeg
```

## AniLiberty

Поддерживаются ссылки на эпизоды вида:

```text
https://www.anilibria.top/anime/video/episode/<id-эпизода>
```

Доступные на странице качества отображаются в программе.
