from app.extensions import db
from app.models import Difficulty, User, Notification
from test_api import _seed_accounts, _login


def test_assign_actions_and_progress(client):
    with client.application.app_context():
        _seed_accounts()
        other=User(name='Responsable',email='other@test.tg',role='administrateur',admin_permissions=['difficultes.view'])
        other.set_password('secret123')
        db.session.add(other)
        db.session.flush()
        other_id=other.id
        depot_id=User.query.filter_by(email='depot@test.tg').first().depot_id
        issue=Difficulty(vendor_phone='22890000001',depot_id=depot_id,category='Matériel',description='Guidon')
        db.session.add(issue);db.session.commit();issue_id=issue.id
    headers=_login(client,'admin@test.tg','secret123')
    payload={'state':'en_cours','action_plan':'Faire réparer le guidon','assigned_admin_id':other_id}
    result=client.patch(f'/api/admin/difficulties/{issue_id}',headers=headers,json=payload)
    assert result.status_code==200
    assert result.json['assigned_admin']['id']==other_id
    assert result.json['action_plan']==payload['action_plan']
    assert result.json['state']=='en_cours'
    assert client.patch(f'/api/admin/difficulties/{issue_id}',headers=headers,json=payload).status_code==200
    with client.application.app_context():
        assert Notification.query.filter_by(recipient_user_id=other_id).count()==1
    payload['state']='resolue'
    assert client.patch(f'/api/admin/difficulties/{issue_id}',headers=headers,json=payload).json['state']=='resolue'
    view_headers=_login(client,'other@test.tg','secret123')
    assert client.patch(f'/api/admin/difficulties/{issue_id}',headers=view_headers,json=payload).status_code==403
    assert client.get('/api/admin/difficulty-assignees',headers=view_headers).status_code==200
    with client.application.app_context():
        db.session.get(User,other_id).admin_permissions=[]
        db.session.commit()
    assert client.patch(f'/api/admin/difficulties/{issue_id}',headers=headers,json=payload).status_code==400
