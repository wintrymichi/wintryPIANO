"""Rappresentazione minima degli eventi MIDI usati dal programma.

Un evento è una tupla ``(tempo_s, tipo, dato1, dato2)``:
- NOTE_ON: dato1 = nota, dato2 = velocity (1-127)
- NOTE_OFF: dato1 = nota, dato2 = 0
- CONTROL: dato1 = numero controller (es. 64 sustain), dato2 = valore
"""

NOTE_ON = 0
NOTE_OFF = 1
CONTROL = 2

CC_SUSTAIN = 64
CC_ALL_NOTES_OFF = 123


def from_mido(msg):
    """Converte un messaggio mido in (tipo, dato1, dato2) oppure None."""
    t = msg.type
    if t == "note_on":
        if msg.velocity == 0:
            return (NOTE_OFF, msg.note, 0)
        return (NOTE_ON, msg.note, msg.velocity)
    if t == "note_off":
        return (NOTE_OFF, msg.note, 0)
    if t == "control_change":
        return (CONTROL, msg.control, msg.value)
    return None
