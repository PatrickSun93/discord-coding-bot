# Discord Coding Bot

> Idiomas: [English](../../README.md) | [简体中文](README.zh-CN.md) | **Español**

Un bot de Discord para enrutar mensajes a backends de programación como **Codex** y **Gemini CLI**.

## Estado actual

Este es un scaffold simple con salida progresiva en Discord.

Backends compatibles:
- `codex`
- `gemini`

## Comandos

- `!help`
- `!backend`
- `!backend codex`
- `!backend gemini`
- `!pwd`
- `!cd <path>`

Cualquier mensaje que no sea un comando se envía al backend seleccionado.

## Configuración

1. Copia el archivo de entorno:

```bash
cp .env.example .env
```

2. Completa:
- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID` opcional
- `DEFAULT_BACKEND`
- `DEFAULT_WORKDIR`
- `CODEX_CMD`
- `CODEX_ARGS` opcional (por defecto: `exec --full-auto`)
- `GEMINI_CMD`

3. Instala dependencias:

```bash
npm install
```

4. Ejecuta:

```bash
npm start
```

## Notas

- La invocación de backends está abstraída en `src/backends/`.
- La salida progresiva en Discord usa lógica compartida de streaming por CLI y ediciones de mensajes con throttling.
- Las respuestas largas se dividen en varios mensajes de Discord cuando hace falta.
- El streaming actual está basado en fragmentos de stdout, no en token streaming.
- La experiencia de streaming depende de cómo el CLI del backend emita stdout. Si el backend solo imprime al final, el usuario seguirá viendo una respuesta final en lugar de progreso real.
- Codex usa por defecto `codex exec --full-auto <prompt>` para una invocación no interactiva más práctica.
- Codex verifica que el directorio de trabajo esté dentro de un repositorio git antes de ejecutarse, porque normalmente espera un contexto de repo confiable.

## Documentación multilingüe

- El `README.md` raíz es la fuente principal.
- Las traducciones viven en `docs/readme/`.
- Cuando cambie el comportamiento, primero actualiza el README en inglés y luego sincroniza las traducciones.

## Próximos pasos razonables

- manejo de argumentos específicos por backend
- persistencia de sesiones
- mejor integración con Codex CLI
- adaptador de Claude Code si hace falta
- streaming opcional de stderr / estado
