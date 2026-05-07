import pyautogui
import random
import time
from pynput import mouse, keyboard

# Configuración
TIEMPO_INACTIVIDAD = 120  # 2 minutos en segundos
INTERVALO_MOVIMIENTO = 5  # Cada cuánto mover el mouse cuando esté inactivo
DISTANCIA_MOVIMIENTO = 20  # Píxeles máximos que se aleja el cursor antes de volver

# Configuración de pausa de almuerzo
HORA_ALMUERZO = (12, 30)   # Hora de inicio del almuerzo (hora, minuto) — 12:30 PM
DURACION_ALMUERZO = 60     # Duración del almuerzo en minutos

screenWidth, screenHeight = pyautogui.size()

class ActivityWatcher:
    def __init__(self):
        self.last_activity_time = time.time()
        self._bot_moving = False  # Flag para ignorar movimientos del bot

        self.mouse_listener = mouse.Listener(
            on_move=self.on_activity,
            on_click=self.on_activity,
            on_scroll=self.on_activity
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_activity
        )

        self.mouse_listener.start()
        self.keyboard_listener.start()

    def on_activity(self, *args):
        # Ignorar eventos generados por el propio bot
        if self._bot_moving:
            return
        self.last_activity_time = time.time()

    def get_idle_time(self):
        return time.time() - self.last_activity_time

    def nudge_mouse(self):
        """Mueve el cursor levemente y lo regresa a la posición original."""
        origin_x, origin_y = pyautogui.position()

        # Calcular destino aleatorio cercano, sin salirse de pantalla
        offset_x = random.randint(-DISTANCIA_MOVIMIENTO, DISTANCIA_MOVIMIENTO)
        offset_y = random.randint(-DISTANCIA_MOVIMIENTO, DISTANCIA_MOVIMIENTO)
        target_x = max(0, min(screenWidth - 1,  origin_x + offset_x))
        target_y = max(0, min(screenHeight - 1, origin_y + offset_y))

        self._bot_moving = True
        try:
            pyautogui.moveTo(target_x, target_y, duration=0.2)
            time.sleep(0.05)
            pyautogui.moveTo(origin_x, origin_y, duration=0.2)
        finally:
            # Siempre liberar el flag, incluso si hay un error
            self._bot_moving = False


def is_lunch_time():
    """Devuelve True si la hora actual está dentro de la ventana de almuerzo."""
    now = time.localtime()
    current_minutes = now.tm_hour * 60 + now.tm_min

    lunch_start = HORA_ALMUERZO[0] * 60 + HORA_ALMUERZO[1]
    lunch_end   = lunch_start + DURACION_ALMUERZO

    return lunch_start <= current_minutes < lunch_end


if __name__ == "__main__":
    watcher = ActivityWatcher()

    print("Script iniciado. El movimiento automático empezará tras 2 minutos de inactividad.")
    print("Rastreando actividad de mouse Y teclado.")
    print(f"Pausa de almuerzo configurada: {HORA_ALMUERZO[0]:02d}:{HORA_ALMUERZO[1]:02d} por {DURACION_ALMUERZO} minutos.")

    try:
        while True:
            segundos_inactivo = watcher.get_idle_time()

            if is_lunch_time():
                print("Hora de almuerzo. Bot pausado.")
                time.sleep(30)  # Revisar cada 30s hasta que termine el almuerzo
            elif segundos_inactivo >= TIEMPO_INACTIVIDAD:
                watcher.nudge_mouse()
                print(f"Inactividad detectada ({int(segundos_inactivo)}s). Cursor movido y regresado.")
                time.sleep(INTERVALO_MOVIMIENTO)
            else:
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nPrograma detenido por el usuario.")


