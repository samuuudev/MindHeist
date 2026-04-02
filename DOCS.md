# MindHeist — Documentación para Administradores

> Guía completa de todos los comandos disponibles del bot competitivo de trivia MindHeist.
> Última actualización: 2 de abril de 2026.

---

## Índice

1. [Configuración inicial](#1-configuración-inicial)
2. [Comandos de jugador](#2-comandos-de-jugador)
   - [/quiz](#quiz)
   - [/daily](#daily)
   - [/streak](#streak)
   - [/rank](#rank)
   - [/top](#top)
   - [/stats](#stats)
   - [/gold](#gold)
   - [/robar](#robar)
   - [/robos](#robos)
   - [/escudo](#escudo)
   - [/estado_escudo](#estado_escudo)
3. [Comandos de administración](#3-comandos-de-administración)
   - [/setup](#setup)
   - [/config](#config)
   - [/set](#set)
   - [/give](#give)
   - [/reset](#reset)
   - [/forcegold](#forcegold)
   - [/sync](#sync)
   - [/status](#status)
4. [Sistema de economía](#4-sistema-de-economía)
5. [Sistema de Preguntas de Oro](#5-sistema-de-preguntas-de-oro)
6. [Sistema de robos](#6-sistema-de-robos)
7. [Sistema de rachas diarias](#7-sistema-de-rachas-diarias)
8. [Notas para administradores](#8-notas-para-administradores)

---

## 1. Configuración inicial

Antes de que el bot funcione correctamente en tu servidor, necesitas ejecutar el comando `/setup` para asignar los canales y roles. Sin esta configuración, algunas funcionalidades (como las Preguntas de Oro y los logs) no estarán operativas.

**Pasos recomendados:**

1. Crea los canales necesarios: uno para quizzes, uno para Preguntas de Oro y uno para logs.
2. Crea los roles que quieras asignar al Top 1, Top 2 y Top 3 del ranking.
3. Ejecuta `/setup` con los canales y roles correspondientes.
4. Verifica la configuración con `/config`.
5. Ajusta parámetros específicos con `/set` si lo necesitas.

---

## 2. Comandos de jugador

Estos comandos están disponibles para todos los miembros del servidor.

---

### `/quiz`

Responde una pregunta de trivia y gana puntos.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `difficulty` | No | Dificultad de la pregunta: **Fácil**, **Media** (por defecto) o **Difícil**. |
| `category` | No | Categoría de la pregunta. Si no se indica, se elige una al azar. |

**Categorías disponibles:**
General, Ciencia, Historia, Geografía, Entretenimiento, Deportes, Lógica, Videojuegos, Literatura, Arte, Música.

**Funcionamiento:**
- El bot genera una pregunta con 4 opciones de respuesta.
- El jugador tiene **30 segundos** para responder pulsando uno de los botones.
- Si acierta, recibe puntos según la dificultad configurada (por defecto: Fácil 3, Media 5, Difícil 8).
- Si falla o no responde a tiempo, no recibe puntos.
- Existe un cooldown entre usos (configurable, por defecto 15 minutos).
- Al usar `/quiz`, hay una probabilidad (configurable) de que se active una Pregunta de Oro.

**Puntos por dificultad (valores por defecto):**

| Dificultad | Puntos |
|------------|--------|
| Fácil | 3 |
| Media | 5 |
| Difícil | 8 |

---

### `/daily`

Responde tu pregunta diaria y mantén tu racha de días consecutivos.

No tiene parámetros.

**Funcionamiento:**
- Cada jugador puede responder una pregunta diaria cada 24 horas (configurable).
- Si aciertas, tu racha sube y recibes puntos base + un bonus acumulativo por racha.
- Si fallas o no respondes a tiempo (60 segundos), **pierdes toda la racha** y vuelves a 0 días.
- Si pasan más de 48 horas sin usar `/daily`, la racha también se pierde.
- Los puntos base son configurables (por defecto 10).
- El bonus de racha crece +2 por día, con un máximo de +20 (a partir del día 11).
- El tiempo para responder es de **60 segundos**.

**Tabla de progresión de racha:**

| Día | Bonus | Total de puntos |
|-----|-------|-----------------|
| 1 | +0 | 10 |
| 2 | +2 | 12 |
| 3 | +4 | 14 |
| 5 | +8 | 18 |
| 7 | +12 | 22 |
| 10 | +18 | 28 |
| 11+ | +20 | 30 (máximo) |

---

### `/streak`

Consulta tu racha diaria actual.

No tiene parámetros.

**Muestra:**
- Tu racha actual en días.
- El bonus de puntos activo.
- Cuándo estará disponible tu próximo `/daily`.
- Un aviso si tu racha está a punto de expirar.
- La tabla de progresión completa.

---

### `/rank`

Mira tu posición en el ranking del servidor.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `member` | No | Usuario del que quieres ver el ranking. Si no se indica, muestra el tuyo. |

**Muestra:**
- Posición en el ranking por puntos.
- Puntos totales.
- Racha diaria.
- Victorias de Oro.
- Precisión (porcentaje de aciertos).
- Actividad de los últimos 7 días.

---

### `/top`

Mira el top de jugadores del servidor.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `category` | No | Tipo de ranking: **Puntos** (por defecto), **Racha Daily**, **Victorias de Oro** o **Precisión**. |
| `page` | No | Página del ranking (10 jugadores por página). |

**Funcionamiento:**
- Muestra un leaderboard paginado con botones para navegar entre páginas.
- Tu nombre aparece destacado en negrita si estás en la página actual.
- Solo aparecen jugadores que hayan participado al menos en un quiz.

---

### `/stats`

Estadísticas detalladas de un jugador.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `member` | No | Usuario del que quieres ver las estadísticas. Si no se indica, muestra las tuyas. |

**Muestra:**
- Puntos, racha, victorias de Oro.
- Precisión global y barra de progreso visual.
- Desglose por tipo de partida (Quiz, Daily, Oro, Robo).
- Tiempo medio de respuesta por tipo.
- Historial de robos: intentos, éxitos, puntos robados, veces robado y puntos perdidos.
- Fecha de registro en el servidor.

---

### `/gold`

Información sobre las Preguntas de Oro y el jackpot actual.

No tiene parámetros.

**Muestra:**
- Jackpot acumulado actualmente.
- Datos de la última Pregunta de Oro (resultado, hace cuánto tiempo).
- Estadísticas globales: total de eventos, porcentaje de acierto, eventos sin ganador.
- Top 5 cazadores de Oro del servidor.
- Explicación del funcionamiento: intervalos, probabilidad, recompensas.

---

### `/robar`

Intenta robar puntos a otro jugador respondiendo una pregunta difícil.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `victim` | Sí | El jugador al que quieres robar. |

**Funcionamiento:**
- Se genera una pregunta de dificultad **hard**.
- Solo el atacante puede responder. Tiene **20 segundos**.
- Si acierta: roba entre el 5% y 20% de los puntos de la víctima (configurable).
- Si falla o no responde: pierde el 10% de sus propios puntos.
- La víctima es notificada en el mismo canal con un mention.
- Existe un cooldown entre robos (configurable, por defecto 60 minutos).
- No se puede robar a uno mismo, a bots, ni a usuarios con escudo activo.
- Los usuarios nuevos (menos de 24 horas en el sistema) tienen protección.
- Tras el intento, se muestra la respuesta correcta si se falló.

**Restricciones:**
- No puedes robarte a ti mismo.
- No puedes robar a un bot.
- No puedes robar a alguien con escudo activo.
- No puedes robar a alguien registrado hace menos de 24 horas.
- Debes esperar el cooldown entre intentos.

---

### `/robos`

Mira tu historial de robos recientes.

No tiene parámetros.

**Muestra:**
- Los últimos 15 robos en los que participaste (como atacante o víctima).
- Para cada robo: resultado, puntos ganados o perdidos, y cuándo ocurrió.

---

### `/escudo`

Compra un escudo temporal contra robos.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `duration` | No | Duración del escudo: **1 hora**, **6 horas** o **24 horas** (por defecto). |

**Funcionamiento:**
- El escudo protege de todos los intentos de robo durante su duración.
- Se paga con puntos del ranking. El coste es de **5 puntos por hora** de protección.
- Solo se puede tener un escudo activo a la vez.
- Si ya tienes un escudo activo, el comando te informará de cuándo expira.

**Costes:**

| Duración | Coste |
|----------|-------|
| 1 hora | 5 puntos |
| 6 horas | 30 puntos |
| 24 horas | 120 puntos |

---

### `/estado_escudo`

Muestra quién tiene escudo activo en el servidor o el estado del escudo de un miembro.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `member` | No | Miembro específico. Si no se indica, lista todos los escudos activos del servidor. |

**Funcionamiento:**
- Sin parámetro: muestra una lista de todos los usuarios con escudo activo y cuándo expira cada uno.
- Con parámetro: muestra si ese usuario tiene escudo y cuándo expira.

---

## 3. Comandos de administración

Estos comandos requieren permisos de **Administrador** en el servidor.

---

### `/setup`

Configuración inicial del bot en el servidor.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `quiz_channel` | No | Canal donde se enviarán los quizzes. |
| `gold_channel` | No | Canal donde aparecerán las Preguntas de Oro. |
| `log_channel` | No | Canal donde el bot registrará toda su actividad. |
| `top1_role` | No | Rol que se asignará automáticamente al jugador en la posición 1 del ranking. |
| `top2_role` | No | Rol para el Top 2. |
| `top3_role` | No | Rol para el Top 3. |

**Notas:**
- Solo necesitas indicar los parámetros que quieras configurar o modificar.
- Puedes ejecutar `/setup` varias veces para actualizar valores individuales.
- Los roles del top se actualizan automáticamente cada 5 minutos.
- Sin `log_channel`, el bot no podrá enviar logs ni novedades automáticas.
- Sin `gold_channel`, las Preguntas de Oro no se enviarán.

---

### `/config`

Ver la configuración actual completa del bot en el servidor.

No tiene parámetros.

**Muestra:**
- Canales configurados (Quiz, Oro, Logs).
- Puntos por actividad (Daily, Quiz, Oro).
- Cooldowns (Daily, Quiz, Robo).
- Configuración de robos (porcentajes de éxito/fallo, puntos mínimos de la víctima).
- Configuración de Preguntas de Oro (intervalos, probabilidad).
- Roles del Top.

---

### `/set`

Modificar un parámetro individual de configuración.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `parameter` | Sí | El parámetro a modificar (se selecciona de una lista). |
| `value` | Sí | El nuevo valor. |

**Parámetros disponibles:**

| Parámetro | Descripción | Rango |
|-----------|-------------|-------|
| Puntos Daily | Puntos base por completar el daily. | 1 — 1000 |
| Puntos Quiz | Puntos base por acertar un quiz. | 1 — 1000 |
| Oro mínimo | Puntos mínimos de recompensa en Pregunta de Oro. | 1 — 10000 |
| Oro máximo | Puntos máximos de recompensa en Pregunta de Oro. | 1 — 10000 |
| Cooldown Quiz (min) | Minutos entre usos de `/quiz`. | 0 — 1440 |
| Cooldown Daily (horas) | Horas entre usos de `/daily`. | 1 — 168 |
| Cooldown Robo (min) | Minutos entre intentos de robo. | 0 — 1440 |
| Puntos mín para robar | Puntos mínimos que debe tener la víctima para ser robada. | 0 — 10000 |
| Intervalo Oro mín (min) | Minutos mínimos entre Preguntas de Oro automáticas. | 1 — 10080 |
| Intervalo Oro máx (min) | Minutos máximos entre Preguntas de Oro automáticas. | 1 — 10080 |
| Chance Oro en Quiz (%) | Probabilidad de que `/quiz` active una Pregunta de Oro. | 0 — 100 |

**Ejemplo:**
```
/set parameter:Cooldown Quiz (min) value:5
```

---

### `/give`

Dar o quitar puntos a un usuario.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `member` | Sí | Usuario objetivo. |
| `amount` | Sí | Cantidad de puntos. Usa valores negativos para quitar. |

**Ejemplos:**
```
/give member:@usuario amount:100     → Da 100 puntos
/give member:@usuario amount:-50     → Quita 50 puntos
```

**Notas:**
- Los puntos nunca bajan de 0.
- Toda modificación queda registrada en transacciones y en el canal de logs.

---

### `/reset`

Resetear datos del servidor.

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `target` | Sí | Qué resetear: **Un usuario**, **Ranking del servidor**, **Historial de respuestas** o **Cooldowns**. |
| `member` | Solo para "Un usuario" | El usuario cuyos datos se van a resetear. |

**Opciones de reset:**

| Opción | Efecto |
|--------|--------|
| Un usuario | Pone a 0 todos los datos del usuario seleccionado (puntos, racha, estadísticas, robos, escudo). Elimina su historial de respuestas, transacciones, robos y roles temporales. |
| Ranking del servidor | Pone a 0 los puntos, racha y victorias de Oro de **todos** los usuarios del servidor. |
| Historial de respuestas | Elimina todo el historial de respuestas del servidor (no afecta puntos ni rachas). |
| Cooldowns | Resetea los cooldowns de daily y robo de todos los usuarios del servidor. |

**Importante:** Todas las opciones excepto "Cooldowns" requieren confirmación mediante botones (Confirmar / Cancelar). Esta acción no se puede deshacer.

---

### `/forcegold`

Forzar una Pregunta de Oro inmediatamente.

No tiene parámetros.

**Funcionamiento:**
- Genera y envía una Pregunta de Oro al canal configurado (`gold_channel`).
- Solo funciona si no hay una Pregunta de Oro activa en ese momento.
- La pregunta funciona igual que las automáticas: todos pueden participar, primer acierto gana.

---

### `/sync`

Sincronizar manualmente los comandos slash del bot con Discord.

No tiene parámetros.

**Uso:** Ejecuta este comando si los comandos no aparecen o están desactualizados tras una actualización del bot.

---

### `/status`

Estado del bot y estadísticas del servidor.

No tiene parámetros.

**Muestra:**
- Usuarios totales y activos (últimos 7 días).
- Partidas totales y partidas de hoy.
- Total de robos y eventos de Oro.
- Jackpot acumulado.
- Preguntas en la base de datos.
- Roles temporales activos.
- Servidores conectados, cogs cargados, latencia y uptime del bot.

---

## 4. Sistema de economía

MindHeist utiliza un sistema de economía unificado basado exclusivamente en **puntos**.

**Formas de ganar puntos:**
- `/quiz` — Respondiendo preguntas de trivia correctamente.
- `/daily` — Completando la pregunta diaria (con bonus por racha).
- Pregunta de Oro — Siendo el primero en acertar una Pregunta de Oro.
- `/robar` — Robando puntos a otros jugadores (si aciertas la pregunta).

**Formas de perder puntos:**
- `/robar` — Si fallas al intentar robar, pierdes el 10% de tus puntos.
- Ser robado — Otro jugador puede robarte entre el 5% y 20% de tus puntos.
- `/escudo` — Comprar un escudo consume puntos.

**Notas:**
- Los puntos nunca bajan de 0.
- No existe moneda secundaria ni sistema de ELO. Todo se mide en puntos.
- Los administradores pueden modificar puntos con `/give`.

---

## 5. Sistema de Preguntas de Oro

Las Preguntas de Oro son eventos especiales con recompensas elevadas.

**Cómo aparecen:**
- Automáticamente cada cierto tiempo (configurable, por defecto entre 60 y 300 minutos).
- Con una probabilidad al usar `/quiz` (configurable, por defecto 5%).
- Forzadas manualmente por un administrador con `/forcegold`.

**Funcionamiento:**
1. La pregunta se envía al canal de Oro configurado.
2. Todos los miembros del servidor pueden participar.
3. Cada persona tiene un único intento.
4. El primero en acertar gana la recompensa (entre 25 y 40 puntos, configurable) más el jackpot acumulado.
5. Si nadie acierta en 30 segundos, la recompensa se acumula como jackpot para la siguiente Pregunta de Oro.

---

## 6. Sistema de robos

Los robos son un sistema PvP donde un jugador puede intentar robar puntos a otro.

**Flujo de un robo:**
1. El atacante usa `/robar @víctima`.
2. Se genera una pregunta de dificultad **hard**.
3. Solo el atacante puede responder. Tiene 20 segundos.
4. Si acierta: roba un porcentaje de los puntos de la víctima (5%-20%, configurable).
5. Si falla: pierde el 10% de sus propios puntos.
6. El resultado se muestra en el canal y se registra en el historial.

**Protecciones:**
- **Escudo** (`/escudo`): protección temporal comprada con puntos.
- **Usuario nuevo**: los jugadores registrados hace menos de 24 horas no pueden ser robados.
- **Cooldown**: hay un tiempo de espera entre intentos de robo (configurable, por defecto 60 minutos).

---

## 7. Sistema de rachas diarias

El sistema de rachas incentiva el uso constante de `/daily`.

**Reglas:**
- Cada día que respondes correctamente tu `/daily`, tu racha sube en 1.
- Si fallas la pregunta o no respondes a tiempo, tu racha vuelve a 0.
- Si pasan más de 48 horas sin usar `/daily`, tu racha también se pierde.
- A mayor racha, mayor bonus de puntos (hasta +20 puntos extra a partir del día 11).

**Indicadores de racha:**

| Racha | Indicador |
|-------|-----------|
| 0 días | `-` |
| 1 día | `.` |
| 3+ días | `\|` |
| 7+ días | `\|\|` |
| 14+ días | `\|\|\|` |
| 30+ días | `MAX` |

**Mensajes de hito:**
- 1 día: "Primer día. Empieza la racha."
- 3 días: "3 días. La constancia paga."
- 7 días: "Una semana entera."
- 14 días: "2 semanas. Leyenda del servidor."
- 30 días: "Un mes completo. Respeto absoluto."

---

## 8. Notas para administradores

### Canales recomendados

| Canal | Uso | Importancia |
|-------|-----|-------------|
| Quiz | Para `/quiz` (opcional, funciona en cualquier canal) | Baja |
| Oro | Donde se envían las Preguntas de Oro automáticas | **Alta** — sin canal, no hay Preguntas de Oro |
| Logs | Registro de toda la actividad del bot | **Alta** — necesario para logs y novedades |

### Permisos del bot

El bot necesita los siguientes permisos en los canales configurados:
- Enviar mensajes.
- Insertar enlaces (embeds).
- Usar emojis externos.
- Leer el historial de mensajes.
- Gestionar roles (solo si usas roles del Top).

### Actualizaciones automáticas

Al reiniciar el bot, si existe contenido en el archivo `updates.txt`, se enviará automáticamente como un mensaje al canal de logs de cada servidor configurado. El archivo se vacía tras el envío.

### Base de datos

- El schema de la base de datos es idempotente: se puede ejecutar múltiples veces sin errores.
- Las preguntas generadas se almacenan en la base de datos para evitar repeticiones.
- Todas las acciones de economía quedan registradas en la tabla de transacciones.

---

> **MindHeist** — Bot competitivo de trivia para Discord.

