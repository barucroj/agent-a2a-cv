import contextvars
import json
import logging

# Se setea al entrar cada request (ver middleware en app/main.py) y se lee
# automaticamente via RequestIdFilter en cada linea de log de esa request,
# sin tener que pasarlo a mano por cada funcion/modulo.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Atributos que ya trae un LogRecord "vacio" -- todo lo demas que aparezca en
# record.__dict__ es un campo agregado via logger.warning(..., extra={...})
# y se incluye tal cual en el JSON de salida.
_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {"message"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and key != "request_id":
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
