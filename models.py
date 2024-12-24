from peewee import *

db = SqliteDatabase('BotDB.db')


class Dish(Model):
    name = TextField()
    price = IntegerField()
    is_kg = BooleanField()

    class Meta:
        database = db


class Order(Model):
    details = TextField()
    total_price = IntegerField()
    address = TextField()
    datetime = TextField()
    phone_number = TextField()

    class Meta:
        database = db


db.create_tables([Dish, Order])

