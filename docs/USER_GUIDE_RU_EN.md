# Task Manager — руководство пользователя / User Guide

---

## Русский

### Что это

Task Manager — приложение для личных и командных задач. Один владелец может запустить сервер на своём компьютере, создавать команды, выдавать задания, назначать баллы и подтверждать выполнение. Участники могут подключаться с компьютера или телефона.

### Установка на Windows

1. Запустите `TaskManagerSetup.exe`.
2. Выберите папку установки и, при необходимости, отметьте создание ярлыка на рабочем столе.
3. Откройте **Task Manager** через ярлык или меню «Пуск».
4. В окне приложения нажмите **Запустить сервер**.
5. Создайте первый аккаунт. Первый человек, который настроит сервер через «Мой сервер», становится его владельцем и администратором.

> Для запуска сервера нужен установленный Docker Desktop. Docker Desktop должен быть открыт и работать.

### Вход и сохранение аккаунта

1. Введите имя пользователя и пароль.
2. Включите **Запомнить меня на этом устройстве**, если не хотите входить заново после перезапуска приложения.
3. Нажмите **Создать аккаунт** для первого входа или **Войти**, если аккаунт уже есть.
4. Кнопка **Выйти** завершает сохранённый вход на этом устройстве.

Пароль не хранится в открытом виде: сервер сохраняет только его защищённый хэш.

### Создание задачи

1. В блоке **Создать задачу** укажите название.
2. При необходимости добавьте описание, тип повторения и число баллов.
3. Выберите вариант:
   - **Личная задача** — видна только вам.
   - **Командная задача** — выберите команду и отметьте ответственных участников.
4. При необходимости включите напоминание и выберите его частоту.
5. Нажмите **Создать задачу**.

### Статусы задач

- **Синяя** — задача создана и ожидает выполнения.
- **Жёлтая** — исполнитель нажал **Выполнено**; задача ожидает подтверждения администратора.
- **Зелёная** — администратор подтвердил выполнение и баллы начислены.

Разовая подтверждённая задача исчезает. Ежедневная и еженедельная задача создаётся снова после соответствующего срока.

### Команды и роли

В разделе **Команды и участники** можно создать команду и выбрать её из списка.

- **Участник** — выполняет назначенные ему задачи и ставит личные напоминания.
- **Менеджер** — создаёт задачи для участников с более низким приоритетом.
- **Администратор команды** — добавляет зарегистрированных пользователей в свою команду и меняет приоритеты.
- **Администратор сервера** — подтверждает выполнение задач, видит административную панель и управляет сервером.

Чтобы добавить человека: выберите команду, нажмите **Добавить участника**, выберите зарегистрированного пользователя, роль и приоритет, затем подтвердите добавление.

### Редактирование и переназначение задач

Администратор может нажать **Изменить** на карточке задачи. Внутри этой же карточки можно поменять:

- название;
- описание;
- баллы;
- ответственного — из списка участников выбранной команды.

После изменений нажмите **Сохранить изменения**. Кнопка **Удалить** окончательно удаляет задачу.

### Подключение телефона и других устройств

1. Администратор открывает **Мой сервер** → панель администратора.
2. Для подключения в одной Wi-Fi сети используйте локальный QR-код.
3. Для подключения из другой сети сначала включите **Доступ из интернета** через Cloudflare Tunnel, затем покажите участнику новый QR-код или адрес.
4. На телефоне откройте приложение, отсканируйте QR-код или введите адрес и код вручную.
5. После успешного подключения адрес сервера сохраняется на устройстве. Нажмите **Сменить сервер**, только если нужно подключиться к другому серверу.

Компьютер владельца, Docker и Tunnel должны оставаться включёнными, пока участники работают через интернет.

### Локальный ИИ-помощник

ИИ работает на компьютере администратора через Ollama: для ответов не используются облачные API-ключи. В панели администратора выберите модель и установите её на диск с достаточным свободным местом.

Примеры команд:

- «Помощник, создай задачу купить продукты»
- «Помощник, назначь задачу подготовить отчёт для Alex»
- «Помощник, переназначь задачу 12 на Косту»
- «Помощник, измени баллы задачи 12 на 5»

Голосовой ввод использует системное распознавание речи устройства. Сам ИИ и данные задач остаются на сервере владельца.

### Безопасность

- Не передавайте свой пароль и QR-код незнакомым людям.
- Для доступа из интернета используйте Cloudflare Tunnel, а не открывайте порт сервера на роутере вручную.
- Не публикуйте файл `.env`, резервные копии базы или папку с данными приложения.
- Регулярно обновляйте Docker Desktop, Windows и приложение.

---

## English

### What it is

Task Manager is an application for personal and team tasks. One owner can run the server on their computer, create teams, assign work, award points, and confirm completion. Participants can connect from a computer or phone.

### Installing on Windows

1. Run `TaskManagerSetup.exe`.
2. Choose an installation folder and optionally create a desktop shortcut.
3. Open **Task Manager** from the shortcut or Start menu.
4. Click **Start server** in the application window.
5. Create the first account. The first person who configures the server through **My server** becomes its owner and administrator.

> Docker Desktop must be installed and running before the server can start.

### Sign-in and remembering an account

1. Enter a username and password.
2. Enable **Remember me on this device** to stay signed in after restarting the application.
3. Click **Create account** for a new account, or **Sign in** for an existing account.
4. **Sign out** removes the saved sign-in from the current device.

Passwords are not stored in plain text. The server stores a protected password hash only.

### Creating a task

1. Enter a title in the **Create task** section.
2. Optionally add a description, recurrence type, and points.
3. Choose one of the following:
   - **Personal task** — visible only to you.
   - **Team task** — select a team and choose the responsible participants.
4. Optionally enable reminders and select a frequency.
5. Click **Create task**.

### Task statuses

- **Blue** — the task is new and waiting to be completed.
- **Yellow** — the assignee clicked **Complete**; the task awaits administrator approval.
- **Green** — an administrator approved the work and points were awarded.

An approved one-time task disappears. Daily and weekly tasks are created again after their respective interval.

### Teams and roles

Use **Teams and participants** to create and select a team.

- **Member** — completes assigned tasks and sets personal reminders.
- **Manager** — creates tasks for participants with a lower priority.
- **Team administrator** — adds registered users to their team and changes priorities.
- **Server administrator** — approves completed tasks, sees the administrator panel, and manages the server.

To add someone: select a team, click **Add participant**, choose a registered user, role, and priority, then confirm.

### Editing and reassigning tasks

An administrator can click **Edit** on a task card. The card expands and allows changing:

- title;
- description;
- points;
- assignee — selected from the team participant list.

Click **Save changes** to apply edits. **Delete** permanently removes a task.

### Connecting phones and other devices

1. The administrator opens **My server** → administrator panel.
2. For devices on the same Wi-Fi network, use the local QR code.
3. For devices on other networks, enable **Internet access** through Cloudflare Tunnel first, then share the new QR code or address.
4. On the phone, open the application and scan the QR code, or enter the address and pairing code manually.
5. After a successful connection, the server address is saved on the device. Use **Change server** only when you need to connect to another server.

The owner’s computer, Docker, and Tunnel must remain running while participants use the server over the internet.

### Local AI assistant

The assistant runs on the administrator’s computer through Ollama. It does not need cloud API keys for responses. In the administrator panel, choose a model and install it on a drive with enough free space.

Example commands:

- “Assistant, create a task to buy groceries”
- “Assistant, assign the report task to Alex”
- “Assistant, reassign task 12 to Kosta”
- “Assistant, change task 12 points to 5”

Voice input uses the device’s system speech recognition. The AI model and task data remain on the owner’s server.

### Security

- Do not share your password or QR code with unknown people.
- For internet access, use Cloudflare Tunnel instead of manually opening router ports.
- Never publish the `.env` file, database backups, or the application data folder.
- Keep Docker Desktop, Windows, and the application up to date.
