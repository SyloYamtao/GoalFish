"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
report_bp = Blueprint('report', __name__)
tasks_bp = Blueprint('tasks', __name__)
prediction_bp = Blueprint('prediction', __name__)
projects_bp = Blueprint('projects', __name__)

from . import graph  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import tasks  # noqa: E402, F401
from . import prediction  # noqa: E402, F401
from . import projects  # noqa: E402, F401
