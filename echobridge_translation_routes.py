"""Pure offline translation routing: never substitute a different source language."""


def plan_translation(source, target, installed, available=()):
    if not source or not target or source == 'auto':
        raise ValueError('Choose a specific source language for translation packages.')
    if source == target:
        return []
    installed, available = set(installed), set(available)
    if (source, target) in installed or (source, target) in available:
        return [(source, target)]
    route = [(source, 'en'), ('en', target)]
    if all(edge in installed or edge in available for edge in route):
        return route
    missing = [f'{a} → {b}' for a, b in route
               if (a, b) not in installed and (a, b) not in available]
    raise RuntimeError('Offline translation route not installed/available. Missing: '
                       + ', '.join(missing))
