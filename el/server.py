
# import urllib library
from urllib.request import urlopen
# import json
import json
import requests
from datetime import datetime, timedelta, timezone
import logging
from slugify import slugify
import pytz
from collections import namedtuple

SOURCE_NAME = "Energi Data Service Tariffer"
BASE_URL = "https://api.energidataservice.dk/dataset/DatahubPricelist"
SPOT_BASE_URL = "https://api.energidataservice.dk/dataset/elspotprices"

INTERVAL = namedtuple("Interval", "price hour")
"""chargeowner =  {
        "gln": "5790000392261",
        "company": "TREFOR El-net A/S",
        "type": ["C"],}
"""
chargeowner =  {
        "gln": "5790000610976",
        "company": "Vores Elnet A/S",
        "type": ["TNT1009"],}


TZ="Europe/Copenhagen"
CURRENCY="DKK"
UNIT="kWh"
REGION="DK1"


_LOGGER = logging.getLogger()
_LOGGER.setLevel(logging.DEBUG)

class ColorMagic:

    def __init__(self,price,date,color):
        self.price = price
        self.date = date
        self.color = color

class Elprices:


    def __init__(self, chargeowner: str | None = None) -> None:
        """Init API connection to Energi Data Service."""
        self.session = requests.Session()
        self._tariffs = {}
        self._tariffs = {}
        self._additional_tariff = {}
        self._all_tariffs = {}
        self._all_additional_tariffs = {}
        self._result = {}
        self.today=None
        self.state=None
        self.tomorrow = None,
        self._today_raw = None,
        self._tomorrow_raw = None,
        self._today_min = 0,
        self._today_max= 0,
        self._today_mean= 0,
        self._tomorrow_min = 0,
        self._tomorrow_max = 0,
        self._tomorrow_mean = 0,
        self.tomorrow_valid=False
        self.source = None
        """
        self._chargeowner = chargeowner

        """

    @property
    def tariffs(self):
        """Return the tariff data."""
        _LOGGER.debug(self._tariffs)

        tariffs = {
            "additional_tariffs": self._additional_tariff,
            "tariffs": self._tariffs,
        }

        return tariffs

    def __entry_in_range(self, entry, check_date) -> bool:
        """Check if an entry is witin the date range."""
        return (entry["ValidFrom"].split("T"))[0] <= check_date and (
            entry["ValidTo"] is None or (entry["ValidTo"].split("T"))[0] > check_date
        )

    @staticmethod
    def _header() -> dict:
        """Create default request header."""
        data = {"Content-Type": "application/json"}
        return data

    def call_api(self, query: str) -> dict:
        """Make the API calls."""
        try:
            headers = self._header()
            resp =  self.session.get(f"{BASE_URL}?{query}", headers=headers)
            resp.raise_for_status()

            if resp.status_code == 400:
                _LOGGER.error("API returned error 400, Bad Request!")
                return {}
            elif resp.status_code == 411:
                _LOGGER.error("API returned error 411, Invalid Request!")
                return {}
            elif resp.status_code == 200:
                res =  resp.json()
                return res["records"]
            else:
                _LOGGER.error("API returned error %s", str(resp.status_code))
                return {}
        except Exception as exc:
            _LOGGER.error("Error during API request: %s", exc)
            raise



    def get_dated_tariff(self, date: datetime) -> dict:
        """Get tariff for this specific date."""
        check_date = date.strftime("%Y-%m-%d")
        tariff_data = {}
        for entry in self._all_tariffs:
            if self.__entry_in_range(entry, check_date):
                baseprice = 0
                for key, val in entry.items():
                    if key == "Price1":
                        baseprice = val
                    if "Price" in key:
                        hour = str(int("".join(filter(str.isdigit, key))) - 1)

                        tariff_data.update(
                            {hour: val if val is not None else baseprice}
                        )

                if len(tariff_data) == 24:
                    return tariff_data

        return {}

    def get_tarrif(self):
        self.get_system_tariffs()
        try:
            """chargeowner = CHARGEOWNERS[self._chargeowner]"""
            limit = "limit=500"
            objfilter = 'filter=%7B"chargetypecode": {},"gln_number": ["{}"]%7D'.format(  # pylint: disable=consider-using-f-string
                str(chargeowner["type"]).replace("'", '"'), chargeowner["gln"]
            )
            sort = "sort=ValidFrom desc"

            query = f"{objfilter}&{sort}&{limit}"
            resp = self.call_api(query)

            if len(resp) == 0:
                _LOGGER.warning(
                    "Could not fetch tariff data from Energi Data Service DataHub!"
                )
                return
            else:
                # We got data from the DataHub - update the dataset
                self._all_tariffs = resp

            # today = datetime.utcnow()
            today = datetime.now(timezone.utc)
            # tomorrow = today + timedelta(days=1)
            # check_date = (datetime.utcnow()).strftime("%Y-%m-%d")
            check_date = today.strftime("%Y-%m-%d")

            tariff_data = {}
            for entry in self._all_tariffs:
                if self.__entry_in_range(entry, check_date):
                    _LOGGER.debug("Found possible dataset: %s", entry)
                    baseprice = 0
                    for key, val in entry.items():
                        if key == "Price1":
                            baseprice = val
                        if "Price" in key:
                            hour = str(int("".join(filter(str.isdigit, key))) - 1)

                            tariff_data.update(
                                {hour: val if val is not None else baseprice}
                            )

                    if len(tariff_data) == 24:
                        self._tariffs = tariff_data
                        break

            _LOGGER.debug(
                "Tariffs:\n%s", json.dumps(self.tariffs, indent=2, default=str)
            )
            return self.tariffs
        except KeyError:
            _LOGGER.error(
                "Error finding '%s' in the list of charge owners - "
                "please reconfigure your integration.",
                self._chargeowner,
            )

    def get_dated_system_tariff(self, date: datetime) -> dict:
        """Get system tariffs for this specific date."""
        check_date = date.strftime("%Y-%m-%d")
        tariff_data = {}
        for entry in self._all_additional_tariffs:
            if self.__entry_in_range(entry, check_date):
                if entry["Note"] not in tariff_data:
                    tariff_data.update(
                        {util_slugify(entry["Note"]): float(entry["Price1"])}
                    )

        return tariff_data

    def get_system_tariffs(self) -> dict:
        """Get additional system tariffs defined by the Danish government."""
        search_filter = '{"Note":["Elafgift","Systemtarif","Transmissions nettarif"]}'
        limit = 500
        query = f"filter={search_filter}&limit={limit}"

        dataset = self.call_api(query)

        if len(dataset) == 0:
            _LOGGER.warning(
                "Could not fetch tariff data from Energi Data Service DataHub!"
            )
            return
        else:
            self._all_additional_tariffs = dataset

        check_date = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        tariff_data = {}
        for entry in self._all_additional_tariffs:
            if self.__entry_in_range(entry, check_date):
                if entry["Note"] not in tariff_data:
                    tariff_data.update(
                        {slugify(entry["Note"]): float(entry["Price1"])}
                    )

        self._additional_tariff = tariff_data

    def _prepare_url(self, url: str) -> str:
        """Prepare and format the URL for the API request."""
        start_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
        start = f"start={str(start_date)}"
        end = f"end={str(end_date)}"
        limit = "limit=150"
        objfilter = (
            f"filter=%7B%22PriceArea%22:%22{REGION}%22%7D"
        )
        sort = "sort=HourUTC%20asc"
        columns = "columns=HourUTC,SpotPriceDKK"

        return f"{url}?{start}&{end}&{objfilter}&{sort}&{columns}&{limit}"
        
    def get_spotprices(self):
        """Fetch latest spotprices, excl. VAT and tariff."""
        headers = self._header()
        url = self._prepare_url(SPOT_BASE_URL)
        _LOGGER.debug(
            "Request body for %s via Energi Data Service API URL: %s",
           REGION,
            url,
        )
        resp =  self.session.get(url, headers=headers)
        if resp.status_code == 400:
            _LOGGER.error("API returned error 400, Bad Request!")
            self._result = {}
        elif resp.status_code == 411:
            _LOGGER.error("API returned error 411, Invalid Request!")
            self._result = {}
        elif resp.status_code == 200:
            res =  resp.json()
            self._result = res["records"]

            _LOGGER.debug(
                "Response for %s:\n%s",
                REGION,
                json.dumps(self._result, indent=2, default=str),
            )
        else:
            _LOGGER.error("API returned error %s", str(resp.status))

    def today_spots(self) -> list:
        """Return raw dataset for today."""
        date = datetime.now().strftime("%Y-%m-%d")
        return self.prepare_data(self._result, date, TZ)

    def tomorrow_spots(self) -> list:
        """Return raw dataset for tomorrow."""
        date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return self.prepare_data(self._result, date, TZ)

    def prepare_data(self,indata, date, tz) -> list:  # pylint: disable=invalid-name
        """Get today prices."""
        local_tz = pytz.timezone(tz)
        reslist = []
        for dataset in indata:
            tmpdate = (
                datetime.fromisoformat(dataset["HourUTC"])
                .replace(tzinfo=pytz.utc)
                .astimezone(local_tz)
            )
            tmp = INTERVAL(dataset["SpotPriceDKK"], local_tz.normalize(tmpdate))
            if date in tmp.hour.strftime("%Y-%m-%d"):
                reslist.append(tmp)

        return reslist

    #TODO do we need this? jdo
    def next_data_refresh(self) -> str:
        """When is next data update?."""
        return f"13:{self._rand_min:02d}:{self._rand_sec:02d}"

    def get_current_price(self) -> None:
        """Get price for current hour."""
        current_state_time = datetime.fromisoformat(
            datetime.now()
            .replace(microsecond=0)
            .replace(second=0)
            .replace(minute=0)
            .isoformat()
        )

        if self.today:
            for dataset in self.today:
                if dataset.hour == current_state_time:
                    self._attr_native_value = dataset.price
                    _LOGGER.debug(
                        "Current price updated to %f for %s",
                        self._attr_native_value,
                        self.region.region,
                    )
                    break

            self._attr_extra_state_attributes = {
                "current_price": self.state,
                "unit": UNIT,
                "currency": CURRENCY,
                "region": REGION,
                "region_code": REGION,
                "tomorrow_valid": self.tomorrow_valid,
                "next_data_update": self.next_data_refresh,
                "today": self.today,
                "tomorrow": self.tomorrow or None,
                "raw_today": self._today_raw or None,
                "raw_tomorrow": self._tomorrow_raw or None,
                "today_min": self._today_min,
                "today_max": self._today_max,
                "today_mean": self._today_mean,
                "tomorrow_min": self._tomorrow_min or None,
                "tomorrow_max": self._tomorrow_max or None,
                "tomorrow_mean": self._tomorrow_mean or None,
                "attribution": f"Data sourced from {self.source}",
            }

            if not isinstance(self.predictions, type(None)):
                self._attr_extra_state_attributes.update(
                    {
                        "forecast": self._add_raw(
                            self.predictions, self._attr_suggested_display_precision
                        ),
                        "attribution": f"Data sourced from {self._api.source} "
                        "and forecast from Carnot",
                    }
                )

            if not isinstance(self._api.tariff_data, type(None)):
                self._attr_extra_state_attributes.update(
                    {
                        "net_operator": self._config.options.get(
                            CONF_TARIFF_CHARGE_OWNER
                        ),
                        "tariffs": show_with_vat(
                            self._api.tariff_data,
                            self._vat,
                            self._attr_suggested_display_precision,
                        ),
                    }
                )
        else:
            self._attr_native_value = None
            _LOGGER.debug("No data found for %s", region)

    def show_with_vat(dataset: dict, vat: float, decimals: int = 3) -> dict:
        """Add vat to the dataset."""
        _LOGGER.debug("Tariff dataset before VAT: %s", dataset)
        out_set = {"additional_tariffs": {}, "tariffs": {}}
        for key, _ in dataset.items():
            if key == "additional_tariffs":
                out_set.update({"additional_tariffs": {}})
                for add_key, add_value in dataset[key].items():
                    out_set["additional_tariffs"].update(
                        {add_key: round(add_value * float(1 + vat), decimals)}
                    )
            elif key == "tariffs":
                for t_key, t_value in dataset[key].items():
                    out_set["tariffs"].update(
                        {t_key: round(t_value * float(1 + vat), decimals)}
                    )

        _LOGGER.debug("Tariff dataset after VAT: %s", out_set)
        return out_set

tarrif=Elprices()
tarrif.get_tarrif()
tarrif.get_spotprices()
tarrif.today = tarrif.today_spots()
tarrif.tomorrow = tarrif.tomorrow_spots()
fixed_additional_tarrifs=0
tariffs_table=tarrif.get_tarrif()

for taxes in tariffs_table['additional_tariffs']:
    fixed_additional_tarrifs=fixed_additional_tarrifs+tariffs_table['additional_tariffs'][taxes]
    

colorMap={};
max_price = float(10000)
min_price = float(10000)

    #Maybe it will break but we pick the hour of the day
    #And with pick that hour base on it's possition in the tarrifs

    #old stuff with class
    #colorMap[price.hour.hour]=ColorMagic(total,price.hour.hour,None)
    #colorMap[price.hour]=ColorMagic(total,price.hour.hour,None)
    #colorMap[price.hour]=total,price.hour.hour

for price in tarrif.today:
    total=price.price/1000+tariffs_table["tariffs"][str(price.hour.hour)]+fixed_additional_tarrifs
    total=total*1.25
    colorMap[price.hour] = total
    

for price in tarrif.tomorrow:
    total=price.price/1000+tariffs_table["tariffs"][str(price.hour.hour)]+fixed_additional_tarrifs
    total=total*1.25
    colorMap[price.hour] = total

max_price = max(colorMap.values())
min_price = min(colorMap.values())

for date in colorMap:
    hourprice = colorMap[date]
    percent = round((hourprice - min_price) / (max_price - min_price),2)
    #print (percent*100)
    percent_diff = 1.0 - percent
    red_color = round(min(255, percent_diff*2 * 255))
    green_color = round(min(255, percent*2 * 255))
    color = (green_color, red_color, 0) #Blue always zero
    print(str(date) + " - " + str(round((hourprice),2)) + " - " + str(color))


#Everytime its run, it takes today and if possible tomorrows prices in the same list. 
#Should be enough.
#Also gives the RGB according to min/max prices for the entire range of values



