import asyncio
import importlib.util
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch, call

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from terminal_app.settings import Settings,parse_partners,validate
from terminal_app.menu import Console,Menu
from terminal_app import runner


class SettingsTests(unittest.TestCase):
    def test_missing_settings_identify_menu_numbers(self):
        self.assertEqual(set(validate(Settings())),{2,3,4})

    def test_invalid_mode_type_delay_and_names(self):
        s=Settings('wrong','custom',4000,[])
        self.assertEqual(set(validate(s)),{2,3,4})
        self.assertEqual(validate(Settings('morning','instant',0,['하늘'])),{})
        self.assertIn(3,validate(Settings('finish','custom',True,['하늘'])))
        self.assertIn(4,validate(Settings('finish','instant',0,'하늘')))

    def test_partner_parser(self):
        self.assertEqual(parse_partners(' 홍길동, 김하늘  이바다 '),['홍길동','김하늘','이바다'])
        for invalid in ('','a b c d','a'*31,'a\x1b[31m'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):parse_partners(invalid)


class MenuTests(unittest.TestCase):
    def make_menu(self,answers,settings=None):
        entries=iter(answers);output=[];run=Mock()
        ui=Console(input_fn=lambda prompt:next(entries),output_fn=output.append)
        return Menu(ui,settings,run),run,output

    def test_start_repairs_missing_settings_before_confirmation(self):
        menu,run,output=self.make_menu(['bad','1','2','','a b c d','하늘,바다','START'])
        menu.start()
        run.assert_called_once()
        s=run.call_args.args[0]
        self.assertEqual((s.ritual,s.speed,s.partners),('morning','instant',['하늘','바다']))
        self.assertTrue(any('설정값에 오류' in line for line in output))
        self.assertTrue(any('개발자는 책임' in line for line in output))

    def test_cancel_settings_never_runs(self):
        menu,run,output=self.make_menu(['0'])
        menu.start();run.assert_not_called()

    def test_only_explicit_start_runs(self):
        for answer in ('','y','yes','1'):
            menu,run,output=self.make_menu([answer],Settings('morning','instant',0,['하늘']))
            menu.start();run.assert_not_called()

    def test_custom_invalid_setting_is_reentered(self):
        menu,run,output=self.make_menu(['3','5000','3','1000','START'],Settings('finish','custom',-1,['하늘']))
        menu.start();run.assert_called_once()
        self.assertEqual(run.call_args.args[0].delay_ms,1000)

    def test_exact_five_menu_entries_and_exit(self):
        menu,run,output=self.make_menu(['5'])
        menu.loop();run.assert_not_called()
        text='\n'.join(output)
        for label in ('1 : Start Write','2 : Morning / Finish','3 : Writing Speed / Type','4 : Partner Name','5 : Exit'):
            self.assertIn(label,text)

    def test_pyfiglet_banner_is_purple_when_enabled(self):
        output=[]
        with patch('pyfiglet.Figlet') as figlet:
            figlet.return_value.renderText.return_value='BANNER\n'
            Console(output_fn=output.append,color=True).banner()
            figlet.assert_called_once_with(font='shadow', width=200)
            figlet.return_value.renderText.assert_called_once_with('AUTO-LITURAL')
        self.assertIn('\033[95mBANNER\033[0m',output)


class TimingTests(unittest.TestCase):
    def test_humanize_randomizes_each_action(self):
        from playwright.async_api import Locator
        action=AsyncMock();sleep=AsyncMock()
        async def sequence():
            await Locator.fill(None,'one');await Locator.fill(None,'two')
        with patch.object(Locator,'fill',action),patch.object(runner.asyncio,'sleep',sleep),patch.object(runner.random,'uniform',side_effect=[6.25,11.5]):
            with runner.writing_timing(Settings('morning','humanize',0,['a']),lambda *_:None):asyncio.run(sequence())
        self.assertEqual(sleep.await_args_list,[call(6.25),call(11.5)])
        self.assertEqual(action.await_count,2)

    def test_instant_never_adds_sleep(self):
        from playwright.async_api import Locator
        with patch.object(Locator,'fill',new_callable=AsyncMock) as action,patch.object(runner.asyncio,'sleep',new_callable=AsyncMock) as sleep:
            with runner.writing_timing(Settings('morning','instant',3000,['a']),lambda *_:None):asyncio.run(Locator.fill(None,'one'))
        action.assert_awaited_once();sleep.assert_not_awaited()

    def test_cancelled_delay_does_not_type_and_restores_method(self):
        from playwright.async_api import Locator
        original=AsyncMock()
        with patch.object(Locator,'fill',original),patch.object(runner.asyncio,'sleep',new_callable=AsyncMock) as sleep:
            sleep.side_effect=asyncio.CancelledError
            with self.assertRaises(asyncio.CancelledError):
                with runner.writing_timing(Settings('morning','custom',300,['a']),lambda *_:None):asyncio.run(Locator.fill(None,'one'))
            self.assertIs(Locator.fill,original)
        original.assert_not_awaited()


class Locator:
    def __init__(self,page,selector):self.page,self.selector=page,selector;self.first=self;self.last=self
    def filter(self,**kw):return self
    def or_(self,other):return self
    async def wait_for(self,**kw):pass
    async def is_visible(self):return False
    async def count(self):return self.page.count
    async def click(self):self.page.clicks.append(self.selector)
    async def check(self):pass
    async def fill(self,value):self.page.fills.append((self.selector,value))


class Page:
    def __init__(self,count):self.count=count;self.clicks=[];self.fills=[]
    def locator(self,selector,**kw):return Locator(self,selector)
    def get_by_role(self,role,name):return Locator(self,name)


class IntegrationTests(unittest.TestCase):
    def test_import_never_prompts_or_opens_chrome(self):
        with patch('builtins.input',side_effect=AssertionError('Unexpected prompt')):
            for mode in ('morning','finish'):
                self.assertTrue(inspect.iscoroutinefunction(runner.prepare(mode).find_button))

    def test_both_rituals_use_local_csv_and_never_final_save(self):
        for mode in ('morning','finish'):
            for count in (1,3):
                with self.subTest(mode=mode,count=count):
                    module=runner.prepare(mode);page=Page(count)
                    with patch('builtins.print'):
                        asyncio.run(module.find_button(page,['test']*count))
                    self.assertTrue(page.fills)
                    self.assertFalse(any('저장' in name for name in page.clicks))

    def test_browser_selection_reuses_authenticated_tab(self):
        from types import SimpleNamespace
        chrome=runner.browser_module()
        def page(url):return SimpleNamespace(url=url,is_closed=lambda:False)
        portal=page('https://aleph-omega.vercel.app/cortex.html')
        browser=SimpleNamespace(contexts=[SimpleNamespace(pages=[portal,page('https://aleph-omega.vercel.app/login')])])
        self.assertIs(chrome.choose_page(browser),portal)
        self.assertFalse(chrome.authenticated('https://evil.example/cortex'))


if __name__=='__main__':unittest.main()
