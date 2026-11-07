"""Minimal representation of the MIDI events used by the program.

An event is a tuple ``(time_s, kind, data1, data2)``:
- NOTE_ON: data1 = note, data2 = velocity (1-127)
- NOTE_OFF: data1 = note, data2 = 0
- CONTROL: data1 = controller number (e.g. 64 sustain), data2 = value
"""

NOTE_ON = 0
NOTE_OFF = 1
CONTROL = 2

CC_SUSTAIN = 64
CC_ALL_NOTES_OFF = 123


def from_mido(msg):
    """Convert a mido message to (kind, data1, data2), or None."""
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
