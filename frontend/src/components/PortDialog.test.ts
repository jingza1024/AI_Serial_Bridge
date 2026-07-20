import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PortDialog from './PortDialog.vue'
import { defaultSerialSettings } from '../composables/useSerial'

describe('PortDialog', () => {
  it('emits profile and reconnect changes through public v-model contracts', async () => {
    const wrapper = mount(PortDialog, {
      props: {
        visible: true,
        ports: [{ device: 'COM14', description: 'Linux console', hwid: 'USB-1' }],
        detectedCount: 1,
        port: 'COM14',
        settings: defaultSerialSettings(),
        profileName: 'Linux board',
        autoReconnect: false,
      },
    })

    await wrapper.get('#profile-name').setValue('Production board')
    await wrapper.get('.auto-reconnect input').setValue(true)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('update:profileName')?.[0]).toEqual(['Production board'])
    expect(wrapper.emitted('update:autoReconnect')?.[0]).toEqual([true])
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })
})
