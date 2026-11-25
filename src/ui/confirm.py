"""Yes/No confirmation pop-ups for actions that reset or discard the user's work."""
from PyQt6.QtWidgets import QMessageBox


def confirm(parent, title, question, detail='', yes_text='Yes', no_text='No'):
    """Ask a yes/no question before an action that resets or discards the user's work.

    No is the default button, so pressing Enter or Esc never confirms by accident.
    macOS hides dialog titles, so the question itself is the bold heading.

    Parameters
    ----------
    parent : QWidget
        Window the dialog belongs to.
    title : str
        Dialog title.
    question : str
        The question, shown as the heading.
    detail : str, optional
        Explanation shown under the question.
    yes_text, no_text : str, optional
        Button texts.

    Returns
    -------
    bool
        True only if the user clicked the yes button.
    """
    box = QMessageBox(QMessageBox.Icon.Question, title, question,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.button(QMessageBox.StandardButton.Yes).setText(yes_text)
    box.button(QMessageBox.StandardButton.No).setText(no_text)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setEscapeButton(QMessageBox.StandardButton.No)
    if detail:
        box.setInformativeText(detail)
    return box.exec() == QMessageBox.StandardButton.Yes
