import json
from datetime import timedelta

import pytest
from django.utils.timezone import now

from pretix.base.models import (
    Checkin, Event, Item, ItemVariation, Order, OrderPosition, Organizer, Team,
    User,
)
from pretix.plugins.pretixdroid.views import API_VERSION


@pytest.fixture
def env():
    o = Organizer.objects.create(name='Dummy', slug='dummy')
    event = Event.objects.create(
        organizer=o, name='Dummy', slug='dummy',
        date_from=now(), plugins='pretix.plugins.banktransfer,pretix.plugins.pretixdroid'
    )
    user = User.objects.create_user('dummy@dummy.dummy', 'dummy')

    t = Team.objects.create(organizer=o, can_change_event_settings=True, can_change_orders=True)
    t.members.add(user)
    t.limit_events.add(event)

    shirt = Item.objects.create(event=event, name='T-Shirt', default_price=12)
    shirt_red = ItemVariation.objects.create(item=shirt, default_price=14, value="Red")
    ItemVariation.objects.create(item=shirt, value="Blue")
    ticket = Item.objects.create(event=event, name='Ticket', default_price=23)
    o1 = Order.objects.create(
        code='FOO', event=event, status=Order.STATUS_PAID,
        datetime=now(), expires=now() + timedelta(days=10),
        total=0, payment_provider='banktransfer'
    )
    op1 = OrderPosition.objects.create(
        order=o1, item=shirt, variation=shirt_red,
        price=12, attendee_name=None, secret='1234'
    )
    op2 = OrderPosition.objects.create(
        order=o1, item=ticket,
        price=23, attendee_name="Peter", secret='5678910'
    )
    return event, user, o1, op1, op2


@pytest.mark.django_db
def test_flush_key(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')
    client.login(email='dummy@dummy.dummy', password='dummy')

    client.get('/control/event/%s/%s/pretixdroid/' % (env[0].organizer.slug, env[0].slug))
    env[0].settings.flush()
    assert env[0].settings.get('pretixdroid_key') == 'abcdefg'

    client.get('/control/event/%s/%s/pretixdroid/?flush_key=1' % (env[0].organizer.slug, env[0].slug))
    env[0].settings.flush()
    assert env[0].settings.get('pretixdroid_key') != 'abcdefg'


@pytest.mark.django_db
def test_custom_datetime(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')
    dt = now() - timedelta(days=1)
    dt = dt.replace(microsecond=0)
    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234', 'datetime': dt.isoformat()})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['version'] == API_VERSION
    assert jdata['status'] == 'ok'
    assert Checkin.objects.last().datetime == dt


@pytest.mark.django_db
def test_only_once(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')

    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['version'] == API_VERSION
    assert jdata['status'] == 'ok'
    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['status'] == 'error'
    assert jdata['reason'] == 'already_redeemed'


@pytest.mark.django_db
def test_reupload_same_nonce(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')

    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234', 'nonce': 'fooobar'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['version'] == API_VERSION
    assert jdata['status'] == 'ok'
    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234', 'nonce': 'fooobar'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['status'] == 'ok'
    assert Checkin.objects.count() == 1


@pytest.mark.django_db
def test_forced_multiple(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')

    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['version'] == API_VERSION
    assert jdata['status'] == 'ok'
    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234', 'force': 'true'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['status'] == 'ok'


@pytest.mark.django_db
def test_require_paid(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')
    env[2].status = Order.STATUS_PENDING
    env[2].save()

    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '1234'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['status'] == 'error'
    assert jdata['reason'] == 'unpaid'


@pytest.mark.django_db
def test_unknown(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')

    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'),
                       data={'secret': '4321'})
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['status'] == 'error'
    assert jdata['reason'] == 'unknown_ticket'


@pytest.mark.django_db
def test_wrong_key(client, env):
    resp = client.post('/pretixdroid/api/%s/%s/redeem/?key=%s' % (env[0].organizer.slug, env[0].slug, '12345'),
                       data={'secret': '4321'})
    assert resp.status_code == 403


@pytest.mark.django_db
def test_unknown_event(client, env):
    resp = client.post('/pretixdroid/api/a/b/redeem/?key=c',
                       data={'secret': '4321'})
    assert resp.status_code == 404


@pytest.mark.django_db
def test_search(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')
    resp = client.get('/pretixdroid/api/%s/%s/search/?key=%s&query=%s' % (
        env[0].organizer.slug, env[0].slug, 'abcdefg', '567891'))
    jdata = json.loads(resp.content.decode("utf-8"))
    assert len(jdata['results']) == 1
    assert jdata['results'][0]['secret'] == '5678910'


@pytest.mark.django_db
def test_download_all_data(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')
    resp = client.get('/pretixdroid/api/%s/%s/download/?key=%s' % (env[0].organizer.slug, env[0].slug, 'abcdefg'))
    jdata = json.loads(resp.content.decode("utf-8"))
    assert len(jdata['results']) == 2
    assert jdata['results'][0]['secret'] == '1234'
    assert jdata['results'][1]['secret'] == '5678910'


@pytest.mark.django_db
def test_status(client, env):
    env[0].settings.set('pretixdroid_key', 'abcdefg')
    Checkin.objects.create(position=env[3])
    resp = client.get('/pretixdroid/api/%s/%s/status/?key=%s' % (
        env[0].organizer.slug, env[0].slug, 'abcdefg'))
    jdata = json.loads(resp.content.decode("utf-8"))
    assert jdata['checkins'] == 1
    assert jdata['total'] == 2
    assert jdata['items'] == [
        {'name': 'T-Shirt',
         'id': env[3].item.pk,
         'checkins': 1,
         'admission': False,
         'total': 1,
         'variations': [
             {'name': 'Red',
              'id': env[3].variation.pk,
              'checkins': 1,
              'total': 1
              },
             {'name': 'Blue',
              'id': env[3].item.variations.get(value='Blue').pk,
              'checkins': 0,
              'total': 0
              }
         ]
         },
        {'name': 'Ticket',
         'id': env[4].item.pk,
         'checkins': 0,
         'admission': False,
         'total': 1,
         'variations': []
         }
    ]
