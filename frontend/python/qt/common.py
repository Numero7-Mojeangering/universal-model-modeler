
from collections.abc import Callable

InspectorKey = tuple[str, str, str, tuple[tuple[str, str | None], ...]]

def slot_ignore_checked(
    fn: Callable[..., object],
    *args: object,
) -> Callable[..., None]:
    """Slot that ignores the 'checked' argument Qt passes to triggered signals."""

    def slot(*_: object) -> None:
        fn(*args)

    return slot