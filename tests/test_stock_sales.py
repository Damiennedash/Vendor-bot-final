from app.extensions import db
from app.models import Sale, SaleLine, Product
from test_api import _seed_accounts, _login


def test_stock_groups_follow_sale_decisions(client, monkeypatch):
    monkeypatch.setattr('app.whatsapp.send_message', lambda *args: True)
    with client.application.app_context():
        own, foreign = _seed_accounts()
        original = db.session.get(Sale, own)
        ids = [own]
        for _ in range(2):
            sale = Sale(vendor_phone=original.vendor_phone, depot_id=original.depot_id, period='Matin', amount=1000)
            db.session.add(sale)
            db.session.flush()
            ids.append(sale.id)
        for sku in ['FANXTRA','FANCHOCO','FANVANILLE']:
            product=Product(sku=sku,name=sku)
            db.session.add(product)
            db.session.flush()
            for sale_id in ids:
                db.session.add(SaleLine(sale_id=sale_id, product_id=product.id, quantity=3, subtotal=0))
        db.session.commit()
    headers=_login(client,'depot@test.tg','secret123')
    summary=client.get('/api/depositaire/summary',headers=headers).json
    assert summary['pending_sales'] == summary['pending_stocks'] == 3
    stocks=client.get('/api/depositaire/stocks?status=en_attente',headers=headers).json
    assert len(stocks)==3 and all(len(row['lines'])==3 for row in stocks)
    assert all(row['quantity']==9 for row in stocks)
    assert client.patch(f'/api/depositaire/stocks/{own}',headers=headers,json={'action':'validate'}).status_code==409
    assert client.patch(f'/api/depositaire/sales/{own}',headers=headers,json={'action':'validate'}).status_code==200
    assert client.patch(f'/api/depositaire/sales/{ids[1]}',headers=headers,json={'action':'reject','reason':'Erreur'}).status_code==200
    summary=client.get('/api/depositaire/summary',headers=headers).json
    assert summary['pending_sales']==summary['pending_stocks']==1
    assert len(client.get('/api/depositaire/stocks?status=en_attente',headers=headers).json)==1
    history=client.get('/api/depositaire/history',headers=headers).json['stocks']
    assert {row['sale_id']:row['status'] for row in history}=={own:'valide',ids[1]:'rejete'}
    assert client.patch(f'/api/depositaire/stocks/{foreign}',headers=headers,json={'action':'validate'}).status_code==404
