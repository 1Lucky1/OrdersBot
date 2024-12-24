import json
import time

from prettytable import PrettyTable
from telebot import TeleBot, types, custom_filters
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage

from models import Dish, Order

# Bot setup
API_TOKEN = '5209136837:AAE6mP9VKwh4bvPnDMrhxlewKES1xAh8GEU'
ADMIN_CHAT_ID = '-1002424728734'
ADMIN_USERS = [890849390, 5983577507]
storage = StateMemoryStorage()
bot = TeleBot(API_TOKEN, state_storage=storage)


class IsAdminFilter(custom_filters.SimpleCustomFilter):
    key = 'is_admin'  # Название фильтра

    def check(self, message):
        # Проверка, если chat_id пользователя в списке авторизованных
        return message.chat.id in ADMIN_USERS


class IsPrivateChatFilter(custom_filters.SimpleCustomFilter):
    key = 'is_private_chat'

    def check(self, message):
        return message.chat.type == 'private'


# States for the bot
class DishStates(StatesGroup):
    name = State()
    price = State()
    unit = State()


class OrderStates(StatesGroup):
    selecting_dishes = State()
    entering_quantity = State()
    confirming_order = State()
    entering_address = State()
    entering_datetime = State()
    entering_phone = State()


def default_markup():
    markup = types.ReplyKeyboardMarkup(is_persistent=True, resize_keyboard=True)

    markup.add(types.KeyboardButton('Меню'))
    markup.add(types.KeyboardButton('Сделать заказ'))

    return markup


def send_long_message(chat_id, text, with_keyboard=False):
    # Разбиваем текст на части по 4095 символов
    chunk_size = 4095
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for chunk in chunks:
        if with_keyboard:
            bot.send_message(chat_id, chunk, parse_mode='HTML', reply_markup=default_markup())
        else:
            bot.send_message(chat_id, chunk, parse_mode='HTML')
        time.sleep(1)  # Задержка в 1 секунду, чтобы избежать ошибки HTTP 429


# Start command
@bot.message_handler(commands=['start'])
def start(message):
    table = PrettyTable()
    table.field_names = ["Название", "Цена", "Единицы измерения"]

    for dish in Dish.select():
        unit = "руб/кг" if dish.is_kg else "руб/шт"
        table.add_row([dish.name, dish.price, unit])

    additional_message = """Заказы принимаю за 2-3 дня до даты отдачи в личные сообщения или же на номер +7949 389 42 15.
    Бесплатная доставка при заказе от 2000 руб. либо самовывоз по договоренности (центр города).
    Меню будет пополняться сезонными блюдами и разными новинками! Следите за обновлениям
                         Bon appétit!"""

    full_message = f"<pre>{table}</pre>\n{additional_message}"

    try:
        if bot.get_state(message.chat.id).split(":")[0] in ["OrderStates", "DishStates"]:
            # Если состояние соответствует, отправляем сообщение с таблицей и дополнительной информацией
            if len(full_message) > 4096:
                send_long_message(message.chat.id, full_message)
            else:
                bot.send_message(message.chat.id, full_message, parse_mode='HTML')
    except AttributeError:
        # В случае ошибки, например, если не удается получить состояние
        if len(full_message) > 4096:
            send_long_message(message.chat.id, full_message, with_keyboard=True)
        else:
            bot.send_message(message.chat.id, full_message, reply_markup=default_markup(), parse_mode='HTML')


# Add dish commands
@bot.message_handler(commands=['add_dish'], is_admin=True)
def add_dish(message):
    bot.set_state(message.from_user.id, DishStates.name, message.chat.id)
    bot.send_message(message.chat.id, "Введите название блюда")


# Remove dish commands
@bot.message_handler(commands=['remove_dish'], is_admin=True)
def remove_dish(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for dish in Dish.select():
        markup.add(types.KeyboardButton(dish.name))

    bot.set_state(message.from_user.id, DishStates.name, message.chat.id)
    bot.add_data(message.from_user.id, message.chat.id, is_delete=True)
    bot.send_message(message.chat.id, "Выберите блюдо для удаления:", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Меню")
def get_menu(message):
    start(message)


@bot.message_handler(state=DishStates.name)
def get_dish_name(message):
    bot.add_data(message.from_user.id, message.chat.id, name=message.text)

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        is_deleting = data.get("is_delete", False)
        if is_deleting:
            try:
                Dish.get(name=message.text).delete_instance()
                bot.send_message(message.chat.id, "Блюдо успешно удалено!")
                bot.delete_state(message.from_user.id, message.chat.id)
                return
            except Dish.DoesNotExist:
                bot.send_message(message.chat.id, "Такого блюда не существует! Попробуйте снова!")
                bot.send_message(message.chat.id, "Выберите блюдо для удаления:")
                return

    bot.set_state(message.from_user.id, DishStates.price, message.chat.id)
    bot.send_message(message.chat.id, "Введите цену блюда")


@bot.message_handler(func=lambda message: message.text == "Завершить выбор блюд", state=OrderStates.selecting_dishes)
def finish_order(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        order_details = data.get('order', {})
        if not order_details:
            bot.send_message(message.chat.id, "Ваш заказ пуст.")
            return

        total_price = sum(item['price'] * item['quantity'] for item in order_details.values())
        summary = "\n".join([f"{item['name']} - {item['quantity']} {item['unit']}" for item in order_details.values()])

    bot.add_data(message.from_user.id, message.chat.id, total_price=total_price, summary=summary)
    bot.set_state(message.from_user.id, OrderStates.confirming_order, message.chat.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Подтвердить", "Отменить")
    bot.send_message(message.chat.id,
                     f"Ваш заказ:\n{summary}\nОбщая стоимость: {total_price} руб.\nПодтвердите заказ или отмените.",
                     reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Подтвердить", state=OrderStates.confirming_order)
def confirm_order(message):
    bot.set_state(message.from_user.id, OrderStates.entering_address, message.chat.id)
    bot.send_message(message.chat.id, "Введите адрес доставки:")


@bot.message_handler(func=lambda message: message.text == "Отменить", state='*')
def cancel_order(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    bot.send_message(message.chat.id, "Заказ отменен.", reply_markup=default_markup())


@bot.message_handler(state=DishStates.price, is_private_chat=True)
def get_dish_price(message):
    try:
        if ',' in message.text:
            price = float(message.text.replace(',', '.'))
        else:
            price = float(message.text)
        bot.add_data(message.from_user.id, message.chat.id, price=price)
        bot.set_state(message.from_user.id, DishStates.unit, message.chat.id)
        bot.send_message(message.chat.id, "Введите единицу измерения (кг или шт)")
    except ValueError:
        bot.send_message(message.chat.id, "Цена должна быть числом. Попробуйте снова.")


@bot.message_handler(state=DishStates.unit, is_private_chat=True)
def get_dish_unit(message):
    unit = message.text
    if unit not in ["кг", "шт"]:
        bot.send_message(message.chat.id, "Неверная единица измерения. Введите 'руб/кг' или 'руб/шт'")
        return

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        is_kg = unit == "руб/кг"
        Dish.create(name=data['name'], price=data['price'], is_kg=is_kg)

    bot.send_message(message.chat.id, "Блюдо успешно добавлено в базу данных!")
    bot.delete_state(message.from_user.id, message.chat.id)


@bot.message_handler(state=DishStates.name, is_private_chat=True)
def handle_remove_dish(message):
    try:
        dish = Dish.get(Dish.name == message.text)
        dish.delete_instance()
        bot.send_message(message.chat.id, "Блюдо удалено.", reply_markup=types.ReplyKeyboardRemove())
    except Dish.DoesNotExist:
        bot.send_message(message.chat.id, "Блюдо не найдено.", reply_markup=types.ReplyKeyboardRemove())
    bot.delete_state(message.from_user.id, message.chat.id)


@bot.message_handler(state=OrderStates.selecting_dishes, is_private_chat=True)
def handle_order_selection(message):
    try:
        dish = Dish.get(Dish.name == message.text)
        bot.add_data(message.from_user.id, message.chat.id, selected_dish=dish.id)
        bot.set_state(message.from_user.id, OrderStates.entering_quantity, message.chat.id)
        unit = "кг" if dish.is_kg else "шт"
        bot.send_message(message.chat.id, f"Введите количество для {dish.name} ({unit}):")
    except Dish.DoesNotExist:
        bot.send_message(message.chat.id, "Блюдо не найдено.")


@bot.message_handler(state=OrderStates.entering_quantity, is_private_chat=True)
def handle_quantity(message):
    try:
        if ',' in message.text:
            quantity = float(message.text.replace(',', '.'))
        else:
            quantity = float(message.text)
        with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
            dish_id = data['selected_dish']
            dish = Dish.get_by_id(dish_id)
            if 'order' not in data:
                data['order'] = {}
            if dish_id not in data['order']:
                data['order'][dish_id] = {'name': dish.name, 'quantity': 0, 'price': dish.price,
                                          'unit': 'кг' if dish.is_kg else 'шт'}
            data['order'][dish_id]['quantity'] += quantity

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Отменить")
        markup.add("Завершить выбор блюд")
        for dish in Dish.select():
            markup.add(types.KeyboardButton(dish.name))

        bot.set_state(message.from_user.id, OrderStates.selecting_dishes, message.chat.id)
        bot.send_message(message.chat.id, "Блюдо добавлено в заказ. Выберите следующее или завершите выбор.",
                         reply_markup=markup)
    except ValueError:
        bot.send_message(message.chat.id, "Количество должно быть числом. Попробуйте снова.")


@bot.message_handler(state=OrderStates.entering_address, is_private_chat=True)
def get_address(message):
    bot.add_data(message.from_user.id, message.chat.id, address=message.text)
    bot.set_state(message.from_user.id, OrderStates.entering_datetime, message.chat.id)
    bot.send_message(message.chat.id, "Введите дату и время доставки (например, 2023-12-31 15:00):")


@bot.message_handler(state=OrderStates.entering_datetime, is_private_chat=True)
def get_datetime(message):
    bot.add_data(message.from_user.id, message.chat.id, datetime=message.text)
    bot.set_state(message.from_user.id, OrderStates.entering_phone, message.chat.id)
    bot.send_message(message.chat.id, "Введите номер телефона:")


@bot.message_handler(state=OrderStates.entering_phone, is_private_chat=True)
def get_phone(message):
    bot.add_data(message.from_user.id, message.chat.id, phone_number=message.text)
    with bot.retrieve_data(message.from_user.id, message.chat.id) as state_data:
        # Запись заказа в базу данных
        data = state_data.copy()

        order_details = json.dumps(data['order'], ensure_ascii=False)
        total_price = data['total_price']
        address = data['address']
        datetime = data['datetime']
        phone_number = data['phone_number']

        new_order = Order.create(
            details=order_details,
            total_price=total_price,
            address=address,
            datetime=datetime,
            phone_number=phone_number
        )

        # Отправка сообщения в специальный чат
    order_summary = f"№ Заказа: {new_order.id}\n" + \
                    "\n".join(
                        [f"{item['name']} - {item['quantity']} {item['unit']}" for item in json.loads(order_details).values()]) + \
                    f"\nОбщая стоимость: {total_price} руб.\n" + \
                    f"Адрес: {address}\nДата и время: {datetime}\nТелефон: {phone_number}"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Заказ выполнен", callback_data=f"complete_{new_order.id}"))

    bot.send_message(ADMIN_CHAT_ID, order_summary, reply_markup=markup)

    bot.send_message(message.chat.id, "Ваш заказ принят!", reply_markup=default_markup())
    bot.delete_state(message.from_user.id, message.chat.id)


@bot.message_handler(func=lambda message: message.text == 'Получить заказы', is_admin=True)
def get_orders(message):
    # Получаем все заказы из базы данных
    orders = Order.select()

    # Если заказов нет
    if not orders:
        bot.send_message(message.chat.id, "Нет заказов.")
        return

    # Для каждого заказа выводим подробности
    for order in orders:
        # Получаем данные заказа
        order_details = json.loads(order.details)
        total_price = order.total_price
        address = order.address
        datetime = order.datetime
        phone_number = order.phone_number

        # Формируем строку для отправки
        order_summary = f"№ Заказа: {order.id}\n" + \
                        "\n".join([f"{item['name']} - {item['quantity']} {item['unit']}" for item in order_details.values()]) + \
                        f"\nОбщая стоимость: {total_price} руб.\n" + \
                        f"Адрес: {address}\nДата и время: {datetime}\nТелефон: {phone_number}"

        # Создаем кнопку для завершения заказа
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Заказ выполнен", callback_data=f"complete_{order.id}"))

        # Отправляем сообщение
        bot.send_message(message.chat.id, order_summary, reply_markup=markup)

        # Задержка в 1 секунду между отправкой сообщений
        time.sleep(1)


# Order handling
@bot.message_handler(func=lambda message: message.text == "Сделать заказ", is_private_chat=True)
def order(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Отменить")
    markup.add("Меню")
    for dish in Dish.select():
        markup.add(types.KeyboardButton(dish.name))

    bot.set_state(message.from_user.id, OrderStates.selecting_dishes, message.chat.id)
    bot.send_message(message.chat.id, "Выберите блюда для заказа или нажмите 'Отменить': ", reply_markup=markup)


# Обработка инлайн-кнопки "Заказ выполнен"
@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_'))
def complete_order(call):
    order_id = int(call.data.split('_')[1])
    try:
        order = Order.get_by_id(order_id)
        order.delete_instance()
        bot.delete_message(call.message.chat.id, call.message.id)
        bot.answer_callback_query(call.id, "Заказ отмечен как выполненный.")
    except Order.DoesNotExist:
        bot.answer_callback_query(call.id, "Заказ не найден.")


bot.add_custom_filter(IsAdminFilter())
bot.add_custom_filter(IsPrivateChatFilter())
bot.add_custom_filter(custom_filters.StateFilter(bot))

bot.infinity_polling()
