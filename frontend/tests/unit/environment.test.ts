import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { VueFlow } from '@vue-flow/core'
import { ElButton } from 'element-plus'

describe('installed frontend environment', () => {
  it('mounts the UI library using Vue in jsdom', () => {
    const wrapper = mount(ElButton, { slots: { default: '环境检查' } })
    expect(wrapper.get('button').text()).toBe('环境检查')
    wrapper.unmount()
  })

  it('loads the production dependency graph component', () => {
    expect(VueFlow).toBeDefined()
  })
})
