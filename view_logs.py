"""Print live client logs. Ctrl+C disconnects the viewer."""
import json
from websockets.sync.client import connect

if __name__ == '__main__':
    try:
        with connect('ws://127.0.0.1:28431/events', proxy=None) as socket:
            for message in socket:
                for event in json.loads(message)['events']:
                    print(f"[{event['client_id']}][{event['level']}] {event['message']}", flush=True)
    except KeyboardInterrupt:
        pass
