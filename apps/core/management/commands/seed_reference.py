"""Starting reference data: countries, the Ukrainian storefront, a draft list of topics and types, and the
Ukrainian cities Harvey knows (with Harvey's Russian spellings as aliases). Safe to run again."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import EventType, Topic
from apps.core.text import norm_key
from apps.geo.models import City, CityAlias, Country
from apps.portals.models import Site, SiteDomain

COUNTRIES = {
    "UA": ({"uk": "Україна", "en": "Ukraine", "pl": "Ukraina"}, "Europe/Kyiv"),
    "PL": ({"uk": "Польща", "en": "Poland", "pl": "Polska"}, "Europe/Warsaw"),
    "MD": ({"uk": "Молдова", "en": "Moldova", "pl": "Mołdawia"}, "Europe/Chisinau"),
    "RO": ({"uk": "Румунія", "en": "Romania", "pl": "Rumunia"}, "Europe/Bucharest"),
}

# official spelling: (en, pl, Harvey's Russian canonical name, importance)
UA_CITIES = {
    "Київ": ("Kyiv", "Kijów", "Киев", 100), "Львів": ("Lviv", "Lwów", "Львов", 60),
    "Одеса": ("Odesa", "Odessa", "Одесса", 60), "Харків": ("Kharkiv", "Charków", "Харьков", 60),
    "Дніпро": ("Dnipro", "Dniepr", "Днепр", 60), "Запоріжжя": ("Zaporizhzhia", "Zaporoże", "Запорожье", 60),
    "Вінниця": ("Vinnytsia", "Winnica", "Винница", 60), "Ужгород": ("Uzhhorod", "Użhorod", "Ужгород", 60),
    "Івано-Франківськ": ("Ivano-Frankivsk", "Iwano-Frankiwsk", "Ивано-Франковск", 60),
    "Тернопіль": ("Ternopil", "Tarnopol", "Тернополь", 60), "Чернівці": ("Chernivtsi", "Czerniowce", "Черновцы", 60),
    "Луцьк": ("Lutsk", "Łuck", "Луцк", 60), "Рівне": ("Rivne", "Równe", "Ровно", 60),
    "Житомир": ("Zhytomyr", "Żytomierz", "Житомир", 60), "Хмельницький": ("Khmelnytskyi", "Chmielnicki", "Хмельницкий", 60),
    "Полтава": ("Poltava", "Połtawa", "Полтава", 60), "Черкаси": ("Cherkasy", "Czerkasy", "Черкассы", 60),
    "Миколаїв": ("Mykolaiv", "Mikołajów", "Николаев", 60), "Мукачево": ("Mukachevo", "Mukaczewo", "Мукачево", 20),
    "Трускавець": ("Truskavets", "Truskawiec", "Трускавец", 20), "Яремче": ("Yaremche", "Jaremcze", "Яремче", 20),
    "Суми": ("Sumy", "Sumy", "Сумы", 60), "Чернігів": ("Chernihiv", "Czernihów", "Чернигов", 60),
    "Кропивницький": ("Kropyvnytskyi", "Kropywnycki", "Кропивницкий", 60), "Херсон": ("Kherson", "Chersoń", "Херсон", 60),
}
EXTRA_ALIASES = {"Київ": ["Kiev", "Киів"], "Одеса": ["Odessa"], "Дніпро": ["Днепропетровск", "Dnepr"]}

TOPICS = [("technology", "Технології", "Technology", "Technologie"), ("business", "Бізнес", "Business", "Biznes"),
          ("marketing", "Маркетинг", "Marketing", "Marketing"), ("education", "Освіта", "Education", "Edukacja"),
          ("culture", "Культура", "Culture", "Kultura"), ("music", "Музика", "Music", "Muzyka"),
          ("health", "Здоров'я", "Health", "Zdrowie"), ("sport", "Спорт", "Sport", "Sport"),
          ("science", "Наука", "Science", "Nauka"), ("family", "Для дітей і сімей", "Kids & family", "Dzieci i rodzina"),
          ("food", "Гастрономія", "Food & drink", "Gastronomia"), ("social", "Суспільство і благодійність",
                                                                    "Society & charity", "Społeczeństwo i dobroczynność")]
TYPES = [("conference", "Конференція", "Conference", "Konferencja"), ("forum", "Форум", "Forum", "Forum"),
         ("meetup", "Мітап", "Meetup", "Meetup"), ("workshop", "Воркшоп / майстер-клас", "Workshop", "Warsztaty"),
         ("training", "Тренінг / курс", "Training", "Szkolenie"), ("webinar", "Вебінар", "Webinar", "Webinar"),
         ("lecture", "Лекція", "Lecture", "Wykład"), ("exhibition", "Виставка", "Exhibition", "Wystawa"),
         ("festival", "Фестиваль", "Festival", "Festiwal"), ("concert", "Концерт", "Concert", "Koncert"),
         ("standup", "Стендап", "Stand-up", "Stand-up"), ("theatre", "Вистава", "Performance", "Spektakl"),
         ("party", "Вечірка", "Party", "Impreza"), ("networking", "Нетворкінг", "Networking", "Networking"),
         ("hackathon", "Хакатон", "Hackathon", "Hackathon"), ("competition", "Змагання / конкурс", "Competition",
                                                              "Zawody / konkurs"),
         ("tour", "Екскурсія", "Tour", "Wycieczka")]


class Command(BaseCommand):
    help = "Довідники для старту: країни, сайт UA, теми й типи (чернетка), міста, які знає Харві"

    def add_arguments(self, parser):
        parser.add_argument("--domain", action="append", default=[],
                            help="Домен сайту UA (можна кілька). За замовчуванням eventcalendar.com.ua")

    @transaction.atomic
    def handle(self, domain, **_):
        for code, (names, tz) in COUNTRIES.items():
            Country.objects.update_or_create(code=code, defaults={"names": names, "timezone": tz})
        ua = Country.objects.get(code="UA")

        site, _ = Site.objects.get_or_create(code="ua", defaults={
            "name": "EventCalendar Україна", "default_locale": "uk", "locales": ["uk", "en", "pl"],
            "timezone": "Europe/Kyiv", "is_default": True})
        site.countries.add(ua)
        defaults = [] if site.domains.exists() else ["eventcalendar.com.ua", "www.eventcalendar.com.ua"]
        for i, host in enumerate(domain or defaults):
            SiteDomain.objects.get_or_create(host=host.lower(), defaults={"site": site, "is_primary": i == 0})

        for i, (code, uk, en, pl) in enumerate(TOPICS):
            Topic.objects.get_or_create(code=code, defaults={"names": {"uk": uk, "en": en, "pl": pl}, "position": i})
        for i, (code, uk, en, pl) in enumerate(TYPES):
            EventType.objects.get_or_create(code=code, defaults={"names": {"uk": uk, "en": en, "pl": pl},
                                                                 "position": i})

        for name, (en, pl, ru, imp) in UA_CITIES.items():
            city = (City.objects.filter(country=ua, name=name, kind__in=["city", "special"])
                    .order_by("-importance").first())
            if city is None:
                city = City.objects.create(country=ua, name=name, kind="special" if name == "Київ" else "city",
                                           names={"en": en, "pl": pl}, importance=imp, timezone="Europe/Kyiv")
            else:
                city.names = {**city.names, "en": en, "pl": pl}
                city.importance = max(city.importance, imp)
                city.save()
            for alias, lang, src in [(name, "uk", "seed"), (en, "en", "seed"), (pl, "pl", "seed"),
                                     (ru, "ru", "harvey")] + [(a, "", "seed") for a in EXTRA_ALIASES.get(name, [])]:
                CityAlias.objects.get_or_create(city=city, key=norm_key(alias),
                                                defaults={"alias": alias, "lang": lang, "source": src})
        self.stdout.write(self.style.SUCCESS(
            f"OK: сайт «{site}», тем {Topic.objects.count()}, типів {EventType.objects.count()}, "
            f"міст {City.objects.filter(country=ua).count()}"))
