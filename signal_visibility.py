"""Exclude entry signals while an existing simulated trade is active."""

def suppress_held_signals(day):
    # Positions exclude trades sold today, so include today's sales explicitly.
    blocked={x['code'] for key in ('positions','buys','sells') for x in day.get(key,[])}
    return [x for x in day.get('signals',[]) if x['code'] not in blocked]
