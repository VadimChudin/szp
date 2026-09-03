"""
Тесты подбора модели под железо.

Клиент видит вердикт ДО оплаты ключа, поэтому ошибка здесь = «купил, а не
работает». Отдельно проверяем слабые конфигурации: 4, 6 и 8 ГБ видеопамяти
встречаются чаще, чем 24.
"""
import pytest

from ai import hw_profile, model_catalog


class TestSelection:
    @pytest.mark.parametrize("vram,expected", [
        (24.0, "qwen3-32b"),
        (48.0, "qwen3-32b"),
        (16.0, "qwen3-14b"),
        (12.0, "qwen3-14b"),
        (11.0, "qwen3-8b"),
        (8.0, "qwen3-8b"),
        (7.0, "qwen3-4b"),
        (6.0, "qwen3-4b"),
    ])
    def test_gpu_tiers(self, vram, expected):
        assert model_catalog.select(vram, 32.0, 200.0).key == expected

    def test_four_gb_card_with_enough_ram_gets_4b(self):
        """4 ГБ видеопамяти: 4B тянется только с выгрузкой части слоёв в RAM."""
        assert model_catalog.select(4.0, 16.0, 200.0).key == "qwen3-4b"

    def test_four_gb_card_with_little_ram_falls_to_smallest(self):
        assert model_catalog.select(4.0, 8.0, 200.0).key == "qwen3-1.7b"

    @pytest.mark.parametrize("ram,expected", [
        (64.0, "qwen3-14b"),
        (32.0, "qwen3-14b"),
        (16.0, "qwen3-8b"),
        (8.0, "qwen3-4b"),
    ])
    def test_cpu_only_tiers(self, ram, expected):
        """Без дискретной карты считаем на процессоре — 6-10 вызовов в сутки."""
        assert model_catalog.select(0.0, ram, 200.0).key == expected

    def test_too_little_ram_is_unsupported(self):
        assert model_catalog.select(0.0, 4.0, 200.0) is None

    def test_disk_shortage_blocks_selection(self):
        """9 ГБ модель не должна начинать качаться на диск с 3 ГБ."""
        assert model_catalog.select(16.0, 32.0, 3.0) is None
        assert model_catalog.select(16.0, 32.0, 200.0) is not None

    def test_disk_check_skipped_when_unknown(self):
        assert model_catalog.select(16.0, 32.0, None) is not None


class TestCatalogIntegrity:
    def test_every_entry_has_real_download(self):
        for spec in model_catalog.CATALOG:
            assert spec.download_bytes > 100 * 1024 * 1024
            assert spec.filename.endswith(".gguf")
            assert spec.repo.startswith("Qwen/")
            assert spec.url.startswith("https://huggingface.co/")

    def test_capability_text_present(self):
        for spec in model_catalog.CATALOG:
            assert spec.capability_text
            assert spec.capability in model_catalog.CAPABILITY_TEXT

    def test_bigger_models_declare_more_capability(self):
        assert model_catalog.BY_KEY["qwen3-14b"].capability == model_catalog.FULL
        assert model_catalog.BY_KEY["qwen3-4b"].capability == model_catalog.BASIC


class TestGpuLayers:
    def test_full_offload_when_vram_is_enough(self):
        spec = model_catalog.BY_KEY["qwen3-8b"]
        assert model_catalog.gpu_layers(spec, 12.0) == -1

    def test_partial_offload_on_small_card(self):
        spec = model_catalog.BY_KEY["qwen3-8b"]
        assert model_catalog.gpu_layers(spec, 5.0) == 20

    def test_cpu_only_when_no_gpu(self):
        spec = model_catalog.BY_KEY["qwen3-4b"]
        assert model_catalog.gpu_layers(spec, 0.0) == 0


class TestProfile:
    def _profile(self, vram=0.0, ram=32.0, disk=500.0):
        profile = hw_profile.Profile(
            gpu_name="RTX 4070" if vram else "", vram_gib=vram,
            ram_gib=ram, free_disk_gib=disk, cpu_name="Test CPU",
            cpu_cores=8)
        profile.model = model_catalog.select(vram, ram, disk)
        return profile

    def test_gpu_summary_mentions_vram(self):
        text = self._profile(vram=12.0).summary()
        assert "RTX 4070" in text and "12" in text

    def test_cpu_summary_mentions_ram(self):
        text = self._profile(vram=0.0, ram=16.0).summary()
        assert "16" in text and "памяти" in text

    def test_verdict_tells_what_to_download(self):
        verdict = self._profile(vram=12.0).verdict()
        assert "Qwen3 14B" in verdict
        assert "ГБ" in verdict

    def test_verdict_explains_refusal(self):
        profile = self._profile(vram=0.0, ram=4.0)
        profile.reason = "Мало оперативной памяти: 4 ГБ"
        assert not profile.supported
        assert "памяти" in profile.verdict()

    def test_to_dict_is_json_ready(self):
        data = self._profile(vram=12.0).to_dict()
        assert data["supported"] is True
        assert data["model"]["key"] == "qwen3-14b"
        assert isinstance(data["vram_gib"], float)


class TestDetectionIsSafe:
    """Определение железа не должно падать ни на какой машине."""

    def test_build_profile_runs_anywhere(self):
        profile = hw_profile.build_profile()
        assert profile.ram_gib >= 0
        assert isinstance(profile.to_dict(), dict)

    def test_ram_detection_returns_number(self):
        assert hw_profile.detect_ram_gib() >= 0

    def test_gpu_detection_returns_tuple(self):
        name, vram = hw_profile.detect_gpu()
        assert isinstance(name, str)
        assert vram >= 0
