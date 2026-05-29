import enum


class EditSource(str, enum.Enum):
    human = "human"
    ai_rewrite = "ai_rewrite"
    revert = "revert"


class SharePermission(str, enum.Enum):
    view = "view"
    edit = "edit"
