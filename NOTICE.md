# Notice

WatchBridge is licensed under the GNU Affero General Public License, version 3 or (at your option) any later
version. See [LICENSE](LICENSE).

## Code derived from Gadgetbridge

The Huawei watch protocol in `daemon/watchbridge/huawei/` is a translation to Python of the Huawei support in
[Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge), which is also licensed AGPL-3.0-or-later.
Ported from Gadgetbridge commit
[`edbea98cbe1377001c0b8154ac20cb930e1db7f6`](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/edbea98cbe1377001c0b8154ac20cb930e1db7f6)
(30 October 2026). The files were translated from Java to Python and modified for WatchBridge in
October and November 2026.

| WatchBridge file | Gadgetbridge source | Copyright |
|---|---|---|
| `huawei/packet.py` | `devices/huawei/HuaweiPacket.java`, `util/CheckSums.java` | © 2015–2025 Andreas Shimokawa, Carsten Pfeiffer, Damien Gaignon, Daniele Gobbetti, José Rebelo, Martin.JM, Petr Vaněk, vappster |
| `huawei/tlv.py` | `devices/huawei/HuaweiTLV.java` | © 2024 Damien Gaignon, Martin.JM, Vitalii Tomin |
| `huawei/crypto.py` | `devices/huawei/HuaweiCrypto.java`, `util/CryptoUtils.java` | © 2021–2024 Andreas Shimokawa, Damien Gaignon, José Rebelo, Martin.JM |
| `huawei/hichain.py` | `service/devices/huawei/requests/GetHiChainRequest.java`, `devices/huawei/packets/DeviceConfig.java` (HiChain) | © 2024 Damien Gaignon, José Rebelo, Martin.JM |
| `huawei/commands.py` | `devices/huawei/packets/DeviceConfig.java`, `Notifications.java`, `Weather.java`, `LocaleConfig.java`, `FindPhone.java`, `AccountRelated.java`, `Calls.java`; `service/devices/huawei/requests/SendNotificationRequest.java`, `StopNotificationRequest.java` (call notifications) | © 2024 Damien Gaignon, José Rebelo, Martin.JM, Vitalii Tomin |
| `huawei/fitness.py` | `devices/huawei/packets/FitnessData.java`, `devices/huawei/HuaweiSampleProvider.java`, `service/devices/huawei/requests/GetFitnessTotalsRequest.java`, `GetStepDataCountRequest.java`, `GetStepDataRequest.java`, `GetSleepDataCountRequest.java`, `GetSleepDataRequest.java` | © 2024 Damien Gaignon, Martin.JM, Vitalii Tomin |
| `huawei/filedownload.py` | `devices/huawei/packets/FileDownloadService2C.java`, `service/devices/huawei/HuaweiFileDownloadManager.java`, `service/devices/huawei/requests/GetFileDownloadInitRequest.java`, `GetFileInfoRequest.java`, `GetFileBlockRequest.java`, `GetFileDownloadCompleteRequest.java` | © 2024 Martin.JM |
| `huawei/healthfiles.py` | `devices/huawei/HuaweiSequenceDataFileParser.java`, `HuaweiSequenceDataParserBase.java`, `HuaweiTrueSleepSequenceDataParser.java`, `HuaweiStressParser.java`, `HuaweiSleepSessionProvider.kt` | © 2025 Me7c7 and Gadgetbridge contributors |
| `huawei/device.py` | `service/devices/huawei/HuaweiSupportProvider.java`, `AsynchronousResponse.java`, `HuaweiWeatherManager.java`, `requests/*` (incl. `onSetCallState` and `handleCallControls` for calls) | © 2024 Damien Gaignon, Martin.JM, Vitalii Tomin |

Gadgetbridge source paths are relative to `app/src/main/java/nodomain/freeyourgadget/gadgetbridge/`.

`tests/test_protocol.py` and `tests/test_fitness.py` use packet test vectors taken from Gadgetbridge's unit tests
(`TestFitnessData.java` © 2022 Martin.JM; same license).

Everything else is original WatchBridge code: the Sailfish OS user interface, the D-Bus service, BlueZ and
RFCOMM handling, notification monitoring, the Open-Meteo client, the pure-Python AES (`huawei/aes.py`) and the
watch simulator used by the tests.

WatchBridge is an independent project. It is not affiliated with or endorsed by the Gadgetbridge project.

## Weather data

Weather data is provided by [Open-Meteo.com](https://open-meteo.com) under the
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) licence. The free Open-Meteo API is intended for
non-commercial use.

## Trademarks

Huawei, Watch GT and HarmonyOS are trademarks of Huawei Technologies Co., Ltd. Sailfish OS is a trademark of
Jolla Ltd. They are used here only to describe compatibility. WatchBridge is not affiliated with or endorsed by
Huawei or Jolla.
