from itertools import permutations
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from config.views import MASTER_USERNAME
from erp.models import DailyActivity, Product, ProductAlias, UserAccessProfile
from erp.quick_orders import parse_quick_order_lines


class FlexibleOrderTests(TestCase):
    def test_all_attribute_orders(self):
        for parts in permutations(["18K", "로즈골드", "코코체인", "42cm", "2개"]):
            with self.subTest(parts=parts):
                rows, invalid = parse_quick_order_lines(" ".join(parts) + " / 연장고리")
                self.assertEqual(invalid, [])
                self.assertEqual(rows[0]["model_number"], "코코체인")
                self.assertEqual(rows[0]["color"], "핑크")
                self.assertEqual(rows[0]["quantity"], Decimal(2))
                self.assertEqual(rows[0]["option_detail"], "연장고리")

    def test_aliases_and_legacy_input(self):
        product = Product.objects.create(code="CHAIN-01", name="체인", unit_price=0)
        for alias in ["코코", "coco"]:
            ProductAlias.objects.create(product=product, alias=alias)
        rows, invalid = parse_quick_order_lines("5미터 코코 18케이 베이지\nCOCO 925실버 5m\n14kp 1.3mm로프 5M")
        self.assertEqual(invalid, [])
        self.assertEqual(rows[0]["model_number"], product.code)
        self.assertEqual(rows[1]["model_number"], product.code)
        self.assertEqual(rows[2]["model_number"], "1.3mm로프")
        rows, invalid = parse_quick_order_lines("COCO 실버 5m")
        self.assertEqual(invalid, [])
        self.assertEqual(rows[0]["model_number"], product.code)

    def test_invalid_lines_are_reported_without_guessing(self):
        examples = ["18k 14k 코코 5m", "18k 핑크 화이트 코코 5m", "18k 코코 0m",
                    "18k 코코 5m 10m", "18k 코코 42cm 0개", "18k 42cm", "18k 코코 -5m",
                    "18k 코코 42cm 2개 3개", "18k 코코 0.001m"]
        for line in examples:
            with self.subTest(line=line):
                self.assertEqual(parse_quick_order_lines(line), ([], [1]))

    def test_attached_legacy_quantities_and_field_limits(self):
        rows, invalid = parse_quick_order_lines("14kp 코코 42cm2개\n18kw 코코 42cmx3")
        self.assertEqual(invalid, [])
        self.assertEqual([r["quantity"] for r in rows], [Decimal(2), Decimal(3)])
        self.assertEqual(parse_quick_order_lines("14kp 코코 42cm / " + "가" * 201), ([], [1]))
        self.assertEqual(parse_quick_order_lines("14kp 코코 42cm", Decimal("1.5")), ([], [1]))


class ActivityPlanTests(TestCase):
    def setUp(self):
        self.master = get_user_model().objects.create_user(username=MASTER_USERNAME)
        self.client.force_login(self.master)

    def test_invalid_date_and_plan_input_do_not_crash_or_erase_content(self):
        for invalid in ["2026-02-30", "wrong-date"]:
            self.assertEqual(self.client.get(reverse("erp:daily_activity_list"), {"date": invalid}).status_code, 200)
            self.assertEqual(self.client.get(reverse("erp:daily_activity_export"), {"date": invalid}).status_code, 400)
            response = self.client.post(reverse("erp:daily_activity_create"), {
                "entry_kind": "plan", "activity_date": invalid, "content": "저장할 계획 내용",
            })
            self.assertContains(response, "저장할 계획 내용", status_code=400)
        self.assertFalse(DailyActivity.objects.exists())

    def test_deleted_activity_cannot_be_updated_and_csrf_is_required(self):
        activity = DailyActivity.objects.create(content="삭제 업무", is_deleted=True)
        response = self.client.post(reverse("erp:daily_activity_update", args=[activity.pk]), {"status": "done", "result": "수정"})
        self.assertEqual(response.status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.master)
        self.assertEqual(csrf_client.post(reverse("erp:daily_activity_create"), {
            "entry_kind": "plan", "activity_date": "2026-09-05", "content": "새 업무",
        }).status_code, 403)

    def test_legacy_activity_post_defaults_to_done(self):
        self.client.post(reverse("erp:daily_activity_create"), {
            "activity_date": "2026-09-05", "content": "기존 앱 행적",
        })
        activity = DailyActivity.objects.get()
        self.assertEqual(activity.status, "done")
        self.assertEqual(activity.content, "기존 앱 행적")

    def test_separate_plan_creation_and_processing_preserve_plan(self):
        response = self.client.post(reverse("erp:daily_activity_create"), {
            "entry_kind": "plan", "return_to": "activity_list",
            "activity_date": "2026-09-05", "content": "직원 주문 교육",
            "status": "done", "result": "계획 등록에서 처리 결과를 저장하지 않음",
        })
        self.assertEqual(response.status_code, 302)
        activity = DailyActivity.objects.get()
        self.assertEqual(activity.status, "planned")
        self.assertEqual(activity.result, "")
        self.assertIsNone(activity.completed_at)
        self.client.post(reverse("erp:daily_activity_update", args=[activity.pk]), {
            "status": "in_progress", "result": "주문 입력 실습 진행", "content": "계획 덮어쓰기 시도",
        })
        activity.refresh_from_db()
        self.assertEqual(activity.content, "직원 주문 교육")
        self.assertEqual(activity.result, "주문 입력 실습 진행")
        page = self.client.get(reverse("erp:daily_activity_list"), {"date": "2026-09-05"})
        self.assertContains(page, 'aria-label="계획란"')
        self.assertContains(page, 'aria-label="처리란"')
        self.assertContains(page, "직원 주문 교육")
        self.assertContains(page, "주문 입력 실습 진행")
        self.assertNotIn("status", page.context["activity_form"].fields)
        self.assertNotIn("result", page.context["activity_form"].fields)
        self.assertEqual(str(page.context["activity_form"]["activity_date"].value()), "2026-09-05")

    def test_plan_complete_and_reopen(self):
        response = self.client.post(reverse("erp:daily_activity_create"), {
            "activity_date": str(timezone.localdate()), "content": "직원 교육 준비", "status": "planned",
        })
        self.assertEqual(response.status_code, 302)
        activity = DailyActivity.objects.get()
        self.assertIsNone(activity.completed_at)
        url = reverse("erp:daily_activity_update", args=[activity.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {"status": "done", "result": "교육 완료"})
        activity.refresh_from_db()
        self.assertIsNotNone(activity.completed_at)
        self.assertEqual(activity.result, "교육 완료")
        self.assertContains(self.client.get(reverse("erp:daily_activity_list")), "교육 완료")
        self.client.post(url, {"status": "in_progress", "result": "추가 교육"})
        activity.refresh_from_db()
        self.assertIsNone(activity.completed_at)
        self.assertEqual(self.client.post(url, {"status": "invalid"}).status_code, 400)

    def test_export_filters_deleted_and_other_dates_and_escapes_formulas(self):
        DailyActivity.objects.create(content="=SUM(1,2)", status="planned")
        DailyActivity.objects.create(content="삭제된 업무", is_deleted=True)
        DailyActivity.objects.create(content="이전 업무", activity_date="2000-01-01")
        response = self.client.get(reverse("erp:daily_activity_export"))
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        self.assertIn("'=SUM(1,2)", text)
        self.assertNotIn("삭제된 업무", text)
        self.assertNotIn("이전 업무", text)

    def test_employee_permissions_and_login(self):
        employee = get_user_model().objects.create_user(username="activity-reader")
        profile, _ = UserAccessProfile.objects.get_or_create(user=employee)
        profile.allowed_sections = ["activities"]
        profile.save()
        self.client.force_login(employee)
        activity = DailyActivity.objects.create(content="업무")
        self.assertEqual(self.client.get(reverse("erp:daily_activity_export")).status_code, 200)
        self.assertEqual(self.client.post(reverse("erp:daily_activity_update", args=[activity.pk]), {"status": "done"}).status_code, 403)
        profile.allowed_sections = []
        profile.save()
        self.assertEqual(self.client.get(reverse("erp:daily_activity_export")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("erp:daily_activity_export")).status_code, 302)
