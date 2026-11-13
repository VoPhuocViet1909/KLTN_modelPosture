"""Profile confirmation/restart and asynchronous session isolation in Qt offscreen."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from ui.workspace_view import WorkspaceDialog
from ui.controller import AppController
from ui.theme import apply_theme
from alerts import machine_device_id
from workspace_profiles import WorkspaceProfiles


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    auth = SimpleNamespace(base_url='http://one.invalid',user_id='owner')
    home, office, key = '11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222','33333333-3333-4333-8333-333333333333'
    device = dict(deviceId=machine_device_id(),deviceKey=key,name='PC',version=2,workspaceId=home,status='ACTIVE')
    choices = dict(device=device,workspace=dict(workspaceId=home,name='Home',status='ACTIVE'),workspaces=[dict(workspaceId=home,name='Home',status='ACTIVE'),dict(workspaceId=office,name='Office',status='ACTIVE'),dict(workspaceId='old',name='Archived',status='ARCHIVED')])
    dialog = WorkspaceDialog(machine_device_id(),dict(name='Home'),lambda:None,lambda:None)
    dialog.show();app.processEvents()
    assert not dialog.apply.isEnabled()
    dialog.set_data(choices)
    assert dialog.choice.count()==3 and dialog.choice.currentData()==home
    dialog.choice.setCurrentIndex(dialog.choice.findData(office))
    first = dialog.payload()
    assert dialog.payload()==first and first[1]['workspaceId']==office
    with tempfile.TemporaryDirectory() as directory:
        profiles = WorkspaceProfiles(str(Path(directory)/'profiles.db'))
        profiles.select(auth,machine_device_id(),home,'Home')
        tasks, stopped, restarted = [], [], []
        controller = SimpleNamespace(auth=auth,_workspace_dialog=dialog,_leaving=False,remember=False,
            _workspace_profiles=lambda:profiles,_track=lambda *args:tasks.append(args),
            _stop_engine=lambda callback:stopped.append(True) or callback(),
            _start_session=lambda *args:restarted.append(args),window=SimpleNamespace(hint=SimpleNamespace(setText=lambda text:None)))
        def open_request(request,**kwargs):
            body = json.loads(request.data)
            return io.BytesIO(json.dumps(dict(body,deviceKey=key,version=body['expectedVersion']+1)).encode())
        auth.open=open_request
        AppController._apply_workspace(controller)
        assert not stopped and profiles.selection(auth,machine_device_id())['workspaceId']==home
        task,done,failed=tasks.pop()
        done(task.fn())
        assert stopped==[True] and restarted==[(auth,False)]
        assert profiles.selection(auth,machine_device_id())['workspaceId']==office
        assert not dialog.isVisible()
        # A response received after account change must not switch cameras/profile.
        dialog.show();dialog.set_data(choices)
        AppController._apply_workspace(controller)
        task,done,failed=tasks.pop()
        controller.auth=object()
        done(task.fn())
        assert len(stopped)==1 and len(restarted)==1
        if len(sys.argv)>1:
            output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
            app.processEvents();assert dialog.grab().save(str(output/'desktop-workspace.png'))
    dialog.close()
    print('PASS: explicit workspace selection, stable retry, stop/restart after receipt, and changed-account callback ignored')


if __name__=='__main__':main()
