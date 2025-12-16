---
title: "Spring IoC Container와 Bean 소개"
date: 2025-12-16 15:00:00 +0900
categories: [Spring Framework, Core Technologies, IoC Container]
tags: [spring, ioc, di, dependency-injection, bean, container, applicationcontext]
---

> 이 글은 [Spring Framework 공식 문서](https://docs.spring.io/spring-framework/reference/core/beans/introduction.html)의 "Introduction to the Spring IoC Container and Beans"를 번역하고 요약한 내용입니다.

## IoC (Inversion of Control)란?

Spring Framework는 **제어의 역전(IoC)** 원칙을 구현한다.

**의존성 주입(DI, Dependency Injection)**은 IoC의 특수한 형태로, 객체가 자신의 의존성(함께 동작하는 다른 객체들)을 다음 방법으로만 정의한다:

- 생성자 인자
- 팩토리 메서드 인자
- 객체 인스턴스 생성 후 설정되는 프로퍼티

IoC 컨테이너는 Bean을 생성할 때 이러한 **의존성을 주입**한다.

이 과정은 Bean이 직접 클래스 생성이나 Service Locator 패턴을 사용해 의존성을 제어하는 것과 정반대이므로 **"제어의 역전(Inversion of Control)"** 이라고 한다.

---

## Spring IoC Container의 핵심 패키지

Spring Framework의 IoC 컨테이너는 다음 두 패키지를 기반으로 한다:

- `org.springframework.beans`
- `org.springframework.context`

### BeanFactory

모든 타입의 객체를 관리할 수 있는 **고급 설정 메커니즘**을 제공하는 인터페이스다.

### ApplicationContext

`BeanFactory`의 하위 인터페이스로, 다음 기능을 추가로 제공한다:

| 기능 | 설명 |
|------|------|
| **AOP 통합** | Spring의 AOP 기능과 쉽게 통합 |
| **메시지 리소스 처리** | 국제화(i18n)를 위한 메시지 처리 |
| **이벤트 발행** | 애플리케이션 이벤트 게시 |
| **특화된 컨텍스트** | 웹 애플리케이션용 `WebApplicationContext` 등 |

> **요약**: `BeanFactory`는 기본 기능과 설정 프레임워크를 제공하고, `ApplicationContext`는 더 많은 엔터프라이즈급 기능을 추가한다. `ApplicationContext`는 `BeanFactory`의 완전한 상위 집합이다.
{: .prompt-info }

---

## Bean이란?

Spring에서 **Bean**은 다음 세 가지 조건을 만족하는 객체다:

1. Spring IoC 컨테이너에 의해 **인스턴스화**됨
2. Spring IoC 컨테이너에 의해 **조립**됨
3. Spring IoC 컨테이너에 의해 **관리**됨

즉, Bean은 애플리케이션의 핵심을 구성하며 **Spring IoC 컨테이너가 관리하는 객체**다.

### Bean과 일반 객체의 차이

| 구분 | 설명 |
|------|------|
| **Bean** | Spring IoC 컨테이너가 생성·관리하는 객체 |
| **일반 객체** | 애플리케이션 내 수많은 객체 중 하나 |

Bean과 Bean 간의 의존성은 **컨테이너가 사용하는 구성 메타데이터(Configuration Metadata)**에 반영된다.

---

## 정리

| 개념 | 설명 |
|------|------|
| **IoC** | 객체가 의존성 제어를 직접 하지 않고, 컨테이너가 주입하는 원칙 |
| **DI** | IoC의 구현 방법. 생성자, 팩토리 메서드, 프로퍼티를 통한 의존성 정의 |
| **BeanFactory** | 기본 IoC 컨테이너 인터페이스 |
| **ApplicationContext** | BeanFactory + AOP + 메시지 처리 + 이벤트 등 엔터프라이즈 기능 |
| **Bean** | Spring IoC 컨테이너가 인스턴스화·조립·관리하는 객체 |

Spring IoC 컨테이너는 구성 메타데이터를 읽어 어떤 객체를 인스턴스화하고, 어떻게 구성하며, 어떻게 조립할지 결정한다.

---

## 참고 자료

- [Spring Framework Reference - IoC Container](https://docs.spring.io/spring-framework/reference/core/beans/introduction.html)
- [Spring Framework Reference - BeanFactory API](https://docs.spring.io/spring-framework/reference/core/beans/beanfactory.html)
