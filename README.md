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

## Запуск на Windows

1. Установите [Python 3](https://www.python.org/downloads/windows/). Во время установки отметьте пункт **Add Python to PATH**.
2. Откройте командную строку: нажмите `Win + R`, введите `cmd` и нажмите `Enter`.
3. В окне командной строки напечатайте `py ` — после команды обязательно оставьте пробел.
4. Перетащите файл `app.py` в окно командной строки. Его полный путь подставится сам.
5. Нажмите `Enter`.

Команда будет выглядеть примерно так:

```bat
py "C:\Users\Ваше имя\Desktop\videograb\app.py"
```

Вместо перетаскивания можно указать путь вручную:

```bat
cd /d "C:\Users\Ваше имя\Desktop\videograb"
py app.py
```

После запуска откройте в браузере [http://localhost:8742](http://localhost:8742), вставьте ссылку и выберите качество.

Для остановки программы вернитесь в командную строку и нажмите `Ctrl + C`.

## Требования

- Python 3
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- ffmpeg — нужен для склейки видео и звука в лучшем качестве, а также для конвертации в MP3

На macOS их можно установить через Homebrew:

```bash
brew install python yt-dlp ffmpeg
```

На Windows после установки Python выполните в командной строке:

```bat
py -m pip install -U yt-dlp
winget install Gyan.FFmpeg
```

## AniLiberty

Поддерживаются ссылки на эпизоды вида:

```text
https://www.anilibria.top/anime/video/episode/<id-эпизода>
```

Доступные на странице качества отображаются в программе.
