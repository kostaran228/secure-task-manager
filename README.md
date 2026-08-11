# Secure Task Manager

Начальная версия API для управления задачами. Проект станет основой портфолио-кейса по Docker, CI/CD, AppSec, Kubernetes и мониторингу.

## Запуск

```powershell
docker compose up --build
```

После запуска API доступен по адресу `http://localhost:8000`, а интерактивная документация — на `/docs`.

## Проверка

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## Тесты

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

После публикации в GitHub workflow автоматически запускает тесты и проверяет сборку Docker-образа для каждого pull request и изменения в основной ветке.

## Безопасность

Отдельный workflow выполняет Semgrep-анализ исходного кода и Trivy-сканирование собранного Docker-образа. Он запускается для pull request, изменений в основной ветке и раз в неделю.

## Наблюдаемость

После `docker compose up --build` доступны:

- Prometheus: `http://localhost:9090`;
- Grafana: `http://localhost:3000`.

API публикует технические метрики на `/metrics`. Учётные данные Grafana в этом демонстрационном запуске задаются в Compose; перед production-деплоем пароль нужно перенести в секреты CI/CD или менеджер секретов.

## Kubernetes

Манифесты в `k8s/` задают развёртывание API с двумя репликами, probes, ограничениями ресурсов, запретом повышения привилегий, Service, Ingress и HPA. Перед применением нужно:

1. опубликовать Docker-образ в GitHub Container Registry;
2. заменить образ в `k8s/api.yaml`;
3. создать реальный Secret на основе `k8s/secret.example.yaml`;
4. заменить домен в `k8s/ingress.yaml`.

## Публикация образа

После размещения репозитория в GitHub тег вида `v0.1.0` запускает release workflow. Он публикует Docker-образ в GitHub Container Registry, откуда его сможет получить Kubernetes-кластер.

## Возможности первой версии

- health-check для мониторинга;
- создание и просмотр задач;
- PostgreSQL в отдельном контейнере;
- запуск всего окружения одной командой.
