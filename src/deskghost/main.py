import pyautogui
import random
import time
from pynput import mouse, keyboard

# ─── Configuración principal ──────────────────────────────────────────────────
TIEMPO_INACTIVIDAD   = 120  # segundos de inactividad antes de mover el mouse
INTERVALO_MOVIMIENTO = 5    # segundos entre movimientos cuando está inactivo
DISTANCIA_MOVIMIENTO = 20   # píxeles máximos del nudge

# ─── Horario laboral (el script se cierra solo fuera de este rango) ───────────
HORA_INICIO = (7,  0)   # 7:00 AM
HORA_FIN    = (18, 0)   # 6:00 PM
DIAS_LABORALES = {0, 1, 2, 3, 4}  # 0=lunes … 4=viernes

# ─── Pausa de almuerzo ────────────────────────────────────────────────────────
HORA_ALMUERZO    = (12, 30)  # inicio del almuerzo (hora, minuto)
DURACION_ALMUERZO = 60       # duración en minutos

# ─── Logging ──────────────────────────────────────────────────────────────────
INTERVALO_LOG = 60  # imprimir mensajes de estado como máximo cada N segundos

# ──────────────────────────────────────────────────────────────────────────────

screenWidth, screenHeight = pyautogui.size()


def minutos_del_dia():
    """Minutos transcurridos desde medianoche."""
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def es_horario_laboral():
    t = time.localtime()
    if t.tm_wday not in DIAS_LABORALES:
        return False
    minutos = minutos_del_dia()
    inicio = HORA_INICIO[0] * 60 + HORA_INICIO[1]
    fin    = HORA_FIN[0]    * 60 + HORA_FIN[1]
    return inicio <= minutos < fin


def es_hora_almuerzo():
    inicio = HORA_ALMUERZO[0] * 60 + HORA_ALMUERZO[1]
    fin    = inicio + DURACION_ALMUERZO
    return inicio <= minutos_del_dia() < fin


class ActivityWatcher:
    def __init__(self):
        self.last_activity_time = time.time()
        self._bot_moving = False

        self.mouse_listener = mouse.Listener(
            on_move=self.on_activity,
            on_click=self.on_activity,
            on_scroll=self.on_activity,
        )
        self.keyboard_listener = keyboard.Listener(on_press=self.on_activity)

        self.mouse_listener.start()
        self.keyboard_listener.start()

    def on_activity(self, *args):
        if self._bot_moving:
            return
        self.last_activity_time = time.time()

    def get_idle_time(self):
        return time.time() - self.last_activity_time

    def reset_idle(self):
        """Reinicia el contador de inactividad (p.ej. al salir del almuerzo)."""
        self.last_activity_time = time.time()

    def nudge_mouse(self):
        """Mueve el cursor levemente y lo regresa a la posición original."""
        origin_x, origin_y = pyautogui.position()
        offset_x = random.randint(-DISTANCIA_MOVIMIENTO, DISTANCIA_MOVIMIENTO)
        offset_y = random.randint(-DISTANCIA_MOVIMIENTO, DISTANCIA_MOVIMIENTO)
        target_x = max(0, min(screenWidth  - 1, origin_x + offset_x))
        target_y = max(0, min(screenHeight - 1, origin_y + offset_y))

        self._bot_moving = True
        try:
            pyautogui.moveTo(target_x, target_y, duration=0.2)
            time.sleep(0.05)
            pyautogui.moveTo(origin_x, origin_y, duration=0.2)
        finally:
            self._bot_moving = False


class ThrottledLogger:
    """Imprime un mensaje sólo si pasaron al menos INTERVALO_LOG segundos desde el último."""
    def __init__(self, intervalo=INTERVALO_LOG):
        self._intervalo = intervalo
        self._last_msg  = {}

    def log(self, key, mensaje):
        ahora = time.time()
        if ahora - self._last_msg.get(key, 0) >= self._intervalo:
            print(mensaje)
            self._last_msg[key] = ahora


def main():

    # ─── Inicio ───────────────────────────────────────────────────────────────────

    watcher = ActivityWatcher()
    logger  = ThrottledLogger()

    print("=" * 55)
    print("  Bot iniciado")
    print(f"  Horario: lun-vie {HORA_INICIO[0]:02d}:{HORA_INICIO[1]:02d} -> {HORA_FIN[0]:02d}:{HORA_FIN[1]:02d}")
    print(f"  Almuerzo: {HORA_ALMUERZO[0]:02d}:{HORA_ALMUERZO[1]:02d} por {DURACION_ALMUERZO} min")
    print(f"  Inactividad umbral: {TIEMPO_INACTIVIDAD}s  |  Intervalo nudge: {INTERVALO_MOVIMIENTO}s")
    print("=" * 55)

    _en_almuerzo = False  # para detectar la transicion salida-de-almuerzo

    try:
        while True:
            # 1. Fuera de horario laboral: terminar el proceso
            if not es_horario_laboral():
                print("Fuera de horario laboral. Bot terminado.")
                break

            # 2. Hora de almuerzo
            if es_hora_almuerzo():
                if not _en_almuerzo:
                    print("Inicio de almuerzo detectado. Previniendo bloqueo de pantalla...")
                    _en_almuerzo = True

                # Nudge silencioso para evitar que la pantalla se bloquee
                watcher.nudge_mouse()
                logger.log("almuerzo", "  [almuerzo] Pantalla mantenida activa.")
                time.sleep(INTERVALO_MOVIMIENTO)

            # 3. Regreso del almuerzo: reiniciar contador
            elif _en_almuerzo:
                print("Fin del almuerzo. Reiniciando contador de inactividad.")
                watcher.reset_idle()
                _en_almuerzo = False
                time.sleep(1)

            # 4. Inactividad normal: nudge
            elif watcher.get_idle_time() >= TIEMPO_INACTIVIDAD:
                watcher.nudge_mouse()
                logger.log(
                    "nudge",
                    f"  [inactivo {int(watcher.get_idle_time())}s] Cursor movido y regresado."
                )
                time.sleep(INTERVALO_MOVIMIENTO)

            # 5. Usuario activo
            else:
                logger.log("activo", "  [activo] Usuario detectado.")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nPrograma detenido manualmente.")
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

